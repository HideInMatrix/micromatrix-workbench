// The runtime package has no declarations; retain Node's spawn overloads.
declare module "cross-spawn" {
  const spawn: typeof import("node:child_process").spawn;
  export default spawn;
}
