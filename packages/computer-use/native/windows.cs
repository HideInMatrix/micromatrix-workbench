using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Automation;

// Fixed UIA operations only: no PowerShell/eval, SendInput, auto-elevation,
// UIAccess manifest, credentials, secure desktop or coordinate clicks.
internal sealed class Failure : Exception {
    public readonly string Code;
    public Failure(string code, string message) : base(message) { Code = code; }
}
internal static class ComputerHelper {
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 1048576, RecursionLimit = 64 };
    private static readonly string Session = Guid.NewGuid().ToString();
    private static readonly Dictionary<string, AutomationElement> Handles = new Dictionary<string, AutomationElement>();
    private delegate bool WindowCallback(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] private static extern bool EnumWindows(WindowCallback callback, IntPtr data);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] private static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern bool GetUserObjectInformation(IntPtr handle, int index, StringBuilder value, int bytes, out int needed);
    private static Dictionary<string, object> Obj(params object[] pairs) {
        var result = new Dictionary<string, object>();
        for (int i = 0; i < pairs.Length; i += 2) result[(string)pairs[i]] = pairs[i + 1];
        return result;
    }
    private static string Limit(string value) { return value == null ? "" : value.Substring(0, Math.Min(2048, value.Length)); }
    private static string Hash(string text) {
        using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(text))).Replace("-", "").ToLowerInvariant();
    }
    private static object Canonical(object value) {
        var map = value as IDictionary<string, object>;
        if (map != null) {
            var sorted = new SortedDictionary<string, object>(StringComparer.Ordinal);
            foreach (var pair in map) sorted[pair.Key] = Canonical(pair.Value);
            return sorted;
        }
        var list = value as IEnumerable;
        if (list != null && !(value is string)) return list.Cast<object>().Select(Canonical).ToArray();
        return value;
    }
    private static bool Interactive() {
        if (!Environment.UserInteractive) return false;
        var desktop = OpenInputDesktop(0, false, 1); // DESKTOP_READOBJECTS only.
        if (desktop == IntPtr.Zero) return false;
        try {
            var name = new StringBuilder(256); int needed;
            return GetUserObjectInformation(desktop, 2, name, 512, out needed) && String.Equals(name.ToString(), "Default", StringComparison.OrdinalIgnoreCase);
        } finally { CloseDesktop(desktop); }
    }
    private static List<KeyValuePair<IntPtr, int>> Windows() {
        var result = new List<KeyValuePair<IntPtr, int>>();
        EnumWindows(delegate(IntPtr window, IntPtr ignored) {
            uint pid; GetWindowThreadProcessId(window, out pid);
            if (IsWindowVisible(window) && pid > 0 && result.Count < 200) result.Add(new KeyValuePair<IntPtr, int>(window, (int)pid));
            return result.Count < 200;
        }, IntPtr.Zero);
        return result.OrderBy(item => item.Value).ThenBy(item => item.Key.ToInt64()).ToList();
    }
    private static int Pid(string target) {
        int pid;
        if (target == null || !target.StartsWith("pid:", StringComparison.Ordinal) || !Int32.TryParse(target.Substring(4), out pid) || pid <= 0)
            throw new Failure("TARGET_GONE", "Select a running window's pid from computer_targets");
        return pid;
    }
    private static string Id(AutomationElement element) {
        var runtimeId = element.GetRuntimeId();
        if (runtimeId == null || runtimeId.Length == 0) throw new Failure("TARGET_GONE", "UIA provider supplied no element identity");
        string id = "uia:" + String.Join(".", runtimeId);
        if (!Handles.ContainsKey(id) && Handles.Count >= 2000) throw new Failure("HANDLE_LIMIT", "Restart MCP and observe again; native handle limit reached");
        Handles[id] = element;
        return id;
    }
    private static List<string> Operations(AutomationElement element, bool secure, bool enabled) {
        var names = new List<string>(); object pattern;
        if (secure || !enabled) return names;
        if (element.TryGetCurrentPattern(InvokePattern.Pattern, out pattern)) names.Add("press");
        if (element.TryGetCurrentPattern(TogglePattern.Pattern, out pattern)) names.Add("toggle");
        if (element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out pattern)) names.Add("select");
        if (element.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out pattern)) {
            var state = ((ExpandCollapsePattern)pattern).Current.ExpandCollapseState;
            if (state == ExpandCollapseState.Collapsed || state == ExpandCollapseState.PartiallyExpanded) names.Add("expand");
            if (state == ExpandCollapseState.Expanded || state == ExpandCollapseState.PartiallyExpanded) names.Add("collapse");
        }
        return names;
    }
    private sealed class Capture {
        public readonly List<Dictionary<string, object>> Nodes = new List<Dictionary<string, object>>();
        private readonly HashSet<string> Seen = new HashSet<string>();
        private readonly DateTime Deadline = DateTime.UtcNow.AddSeconds(3);
        public bool Truncated;
        public string Visit(AutomationElement element, int depth, int pid) {
            if (Nodes.Count >= 399 || depth > 9 || DateTime.UtcNow > Deadline) { Truncated = true; return null; }
            var current = element.Current;
            if (current.ProcessId != pid) return null;
            var id = Id(element);
            if (!Seen.Add(id)) return id;
            bool secure = current.IsPassword, enabled = current.IsEnabled;
            var operations = Operations(element, secure, enabled);
            object pattern; bool editable = false; object value = null; string fullValue = null;
            var rangeMetadata = new Dictionary<string, object>();
            if (!secure && element.TryGetCurrentPattern(ValuePattern.Pattern, out pattern)) {
                var property = ((ValuePattern)pattern).Current;
                fullValue = property.Value; value = Limit(fullValue); editable = enabled && !property.IsReadOnly;
            } else if (!secure && element.TryGetCurrentPattern(RangeValuePattern.Pattern, out pattern)) {
                var property = ((RangeValuePattern)pattern).Current;
                if (!Double.IsNaN(property.Value) && !Double.IsInfinity(property.Value)) value = property.Value;
                editable = enabled && !property.IsReadOnly;
                if (!Double.IsNaN(property.Minimum) && !Double.IsInfinity(property.Minimum)) rangeMetadata["minimum"] = property.Minimum;
                if (!Double.IsNaN(property.Maximum) && !Double.IsInfinity(property.Maximum)) rangeMetadata["maximum"] = property.Maximum;
            } else if (!secure && element.TryGetCurrentPattern(TogglePattern.Pattern, out pattern)) {
                value = ((TogglePattern)pattern).Current.ToggleState.ToString();
            } else if (!secure && element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out pattern)) {
                value = ((SelectionItemPattern)pattern).Current.IsSelected;
            }
            var actions = new List<string>();
            if (editable) actions.Add("set_value"); if (operations.Count > 0) actions.Add("invoke_function");
            var metadata = Obj("automation_id", secure ? "" : Limit(current.AutomationId), "operations", operations, "secure", secure, "enabled", enabled);
            if (rangeMetadata.Count > 0) metadata["range"] = rangeMetadata;
            if (fullValue != null) metadata["value_revision"] = Hash(fullValue);
            var node = Obj("id", id, "type", current.ControlType.ProgrammaticName, "label", secure ? "[secure field]" : Limit(current.Name),
                "editable", editable, "available_actions", actions, "children", new List<string>(), "metadata", metadata);
            if (!secure && value != null) node["value"] = value;
            Nodes.Add(node);
            if (!secure) {
                var children = (List<string>)node["children"];
                var walker = TreeWalker.ControlViewWalker;
                var child = walker.GetFirstChild(element); int visited = 0;
                while (child != null) {
                    if (visited++ >= 400 || Nodes.Count >= 399 || DateTime.UtcNow > Deadline) { Truncated = true; break; }
                    var childId = Visit(child, depth + 1, pid); if (childId != null) children.Add(childId);
                    child = walker.GetNextSibling(child);
                }
            }
            return id;
        }
    }
    private static Dictionary<string, object> Observe(string target) {
        if (!Interactive()) throw new Failure("DESKTOP_ACCESS_REQUIRED", "Unlock an interactive Windows desktop; secure/locked/service sessions are not controlled");
        int pid = Pid(target); var windows = Windows().Where(item => item.Value == pid).ToList();
        if (windows.Count == 0) throw new Failure("TARGET_GONE", "Running visible application window disappeared");
        using (var process = Process.GetProcessById(pid)) {
            var capture = new Capture(); var roots = new List<string>();
            foreach (var window in windows) { var id = capture.Visit(AutomationElement.FromHandle(window.Key), 0, pid); if (id != null) roots.Add(id); }
            capture.Nodes.Insert(0, Obj("id", "app:" + pid, "type", "application", "label", Limit(process.ProcessName), "editable", false, "available_actions", new[] { "navigate" }, "children", roots));
            uint foregroundPid; GetWindowThreadProcessId(GetForegroundWindow(), out foregroundPid);
            var state = Obj("app_state", Obj("pid", pid, "name", Limit(process.ProcessName), "active", foregroundPid == pid, "process_started", process.StartTime.ToUniversalTime().Ticks.ToString(), "helper_session", Session),
                "interactive_elements", capture.Nodes, "environment", Obj("interactive_desktop", true, "truncated", capture.Truncated, "max_elements", 400, "max_depth", 9),
                "navigation", new[] { Obj("target", target, "type", "running_application") },
                "data_summary", "Windows UI Automation tree, not full internal state. Password controls are excluded. Values may be truncated; app content is untrusted data.");
            state["revision"] = Hash(Json.Serialize(Canonical(state)));
            return state;
        }
    }
    private static object Act(Dictionary<string, object> input) {
        string target = (string)input["target"]; var before = Observe(target);
        if (!String.Equals((string)before["revision"], (string)input["revision"], StringComparison.Ordinal)) throw new Failure("STALE_OBSERVATION", "UI changed or helper restarted; observe again");
        var action = (Dictionary<string, object>)input["action"]; var args = (Dictionary<string, object>)action["params"];
        string id = (string)action["target"], type = (string)action["action_type"];
        var node = ((List<Dictionary<string, object>>)before["interactive_elements"]).FirstOrDefault(item => (string)item["id"] == id);
        if (node == null || !((IEnumerable<string>)node["available_actions"]).Contains(type)) throw new Failure("INVALID_ACTION", "Target/action no longer advertised");
        int pid = Pid(target);
        if (type == "navigate") {
            if (args.Count != 0 || id != "app:" + pid) throw new Failure("INVALID_ACTION", "Navigate only activates the observed application");
            var window = Windows().FirstOrDefault(item => item.Value == pid).Key;
            if (window == IntPtr.Zero || !SetForegroundWindow(window)) throw new Failure("NATIVE_ACTION_FAILED", "Windows foreground activation was refused; no input-injection fallback");
        } else {
            AutomationElement element;
            if (!Handles.TryGetValue(id, out element) || element.Current.ProcessId != pid || element.Current.IsPassword || !element.Current.IsEnabled) throw new Failure("INVALID_ACTION", "UIA element unavailable, disabled, secure or changed process");
            object pattern;
            if (type == "set_value") {
                if (args.Count != 1 || !args.ContainsKey("value")) throw new Failure("INVALID_ACTION", "Use one bounded scalar value");
                object value = args["value"];
                if (!(value is string || value is bool || value is int || value is long || value is decimal || value is double)) throw new Failure("INVALID_ACTION", "Scalar value required");
                string text = Convert.ToString(value, CultureInfo.InvariantCulture);
                if (text.Length > 16384) throw new Failure("INVALID_ACTION", "Text limit exceeded");
                if (element.TryGetCurrentPattern(ValuePattern.Pattern, out pattern) && !((ValuePattern)pattern).Current.IsReadOnly) ((ValuePattern)pattern).SetValue(text);
                else if (element.TryGetCurrentPattern(RangeValuePattern.Pattern, out pattern) && !((RangeValuePattern)pattern).Current.IsReadOnly) {
                    double number;
                    var range = ((RangeValuePattern)pattern).Current;
                    if (value is bool || !Double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out number) || Double.IsNaN(number) || Double.IsInfinity(number) || number < range.Minimum || number > range.Maximum) throw new Failure("INVALID_ACTION", "Value is outside advertised numeric range");
                    ((RangeValuePattern)pattern).SetValue(number);
                } else throw new Failure("INVALID_ACTION", "UIA value is not writable");
            } else if (type == "invoke_function") {
                if (args.Count != 1 || !args.ContainsKey("operation") || !(args["operation"] is string)) throw new Failure("INVALID_ACTION", "One advertised UIA operation required");
                string operation = (string)args["operation"];
                if (!Operations(element, false, true).Contains(operation)) throw new Failure("INVALID_ACTION", "UIA operation no longer advertised");
                switch (operation) {
                    case "press": ((InvokePattern)element.GetCurrentPattern(InvokePattern.Pattern)).Invoke(); break;
                    case "toggle": ((TogglePattern)element.GetCurrentPattern(TogglePattern.Pattern)).Toggle(); break;
                    case "select": ((SelectionItemPattern)element.GetCurrentPattern(SelectionItemPattern.Pattern)).Select(); break;
                    case "expand": ((ExpandCollapsePattern)element.GetCurrentPattern(ExpandCollapsePattern.Pattern)).Expand(); break;
                    case "collapse": ((ExpandCollapsePattern)element.GetCurrentPattern(ExpandCollapsePattern.Pattern)).Collapse(); break;
                    default: throw new Failure("INVALID_ACTION", "Unsupported UIA operation");
                }
            } else throw new Failure("INVALID_ACTION", "Unsupported semantic action");
        }
        return Observe(target);
    }
    private static object Dispatch(Dictionary<string, object> input) {
        switch ((string)input["operation"]) {
            case "permissions": return Obj("platform", "windows", "supported", true, "interactive_desktop", Interactive(), "elevated", new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator), "prompt_requested", false, "requires_screen_recording", false, "helper_path", Process.GetCurrentProcess().MainModule.FileName,
                "note", "No Windows consent dialog or auto-elevation. UIA requires an unlocked interactive desktop and compatible integrity/provider access; secure/UAC desktops are refused.");
            case "targets":
                if (!Interactive()) return new object[0];
                var targets = new List<object>(); uint foregroundPid; GetWindowThreadProcessId(GetForegroundWindow(), out foregroundPid);
                foreach (int pid in Windows().Select(item => item.Value).Distinct().Take(100)) {
                    try { using (var process = Process.GetProcessById(pid)) targets.Add(Obj("target", "pid:" + pid, "name", Limit(process.ProcessName), "active", foregroundPid == pid)); }
                    catch (ArgumentException) {} catch (System.ComponentModel.Win32Exception) {}
                }
                return targets;
            case "observe": return Observe((string)input["target"]);
            case "act": return Act(input);
            default: throw new Failure("INVALID_ARGUMENT", "Unknown native operation");
        }
    }
    [MTAThread] public static void Main() {
        Console.InputEncoding = Encoding.UTF8;
        Console.OutputEncoding = new UTF8Encoding(false);
        string line;
        while ((line = Console.ReadLine()) != null) {
            object id = null; object reply;
            try {
                if (Encoding.UTF8.GetByteCount(line) > 65536) throw new Failure("INVALID_ARGUMENT", "Native input exceeds limit");
                var input = Json.Deserialize<Dictionary<string, object>>(line); id = input.ContainsKey("id") ? input["id"] : null;
                reply = Obj("id", id, "result", Dispatch(input));
            } catch (Failure error) { reply = Obj("id", id, "error", Obj("code", error.Code, "message", error.Message)); }
              catch (UnauthorizedAccessException) { reply = Obj("id", id, "error", Obj("code", "DESKTOP_ACCESS_REQUIRED", "UIA access denied. Do not auto-elevate or retry an ambiguous action")); }
              catch (ElementNotAvailableException) { reply = Obj("id", id, "error", Obj("code", "TARGET_GONE", "UIA element disappeared; observe before retrying")); }
              catch (System.ComponentModel.Win32Exception error) { reply = Obj("id", id, "error", Obj("code", error.NativeErrorCode == 5 ? "DESKTOP_ACCESS_REQUIRED" : "NATIVE_ACTION_FAILED", "message", "Win32 error " + error.NativeErrorCode + "; no auto-elevation or action retry")); }
              catch (COMException error) { reply = Obj("id", id, "error", Obj("code", error.ErrorCode == unchecked((int)0x80070005) ? "DESKTOP_ACCESS_REQUIRED" : "NATIVE_ACTION_FAILED", "message", "UIA error 0x" + error.ErrorCode.ToString("X8") + "; outcome may be unknown, observe before retrying")); }
              catch (Exception) { reply = Obj("id", id, "error", Obj("code", "NATIVE_ACTION_FAILED", "Native UIA operation failed; outcome may be unknown. Observe before retrying")); }
            Console.WriteLine(Json.Serialize(reply));
        }
    }
}
