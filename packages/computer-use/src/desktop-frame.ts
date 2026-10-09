import { z } from "zod";
import { fail } from "./protocol.js";

export const rectangle = z.object({x:z.number().finite(),y:z.number().finite(),width:z.number().positive().max(32_768),height:z.number().positive().max(32_768)}).strict();
export const frameSchema = z.object({revision:z.string().regex(/^[0-9a-f]{64}$/),width:z.number().int().positive().max(1280),height:z.number().int().positive().max(1280),
  bounds:rectangle,data:z.string().min(4).max(524_288),mimeType:z.literal("image/jpeg")}).strict();
export const ocrSchema = z.array(z.object({text:z.string().min(1).max(2048),confidence:z.number().min(0).max(1),bounds:rectangle}).strict()).max(200);
const pointer = {x:z.number().int().min(0).max(1279),y:z.number().int().min(0).max(1279)};
const keys = ["enter","escape","tab","backspace","delete","left","right","up","down","space","home","end","page_up","page_down","a","c","v","x","z"] as const;
export const visualParams = z.discriminatedUnion("operation",[
  z.object({operation:z.literal("click"),...pointer}).strict(),
  z.object({operation:z.literal("scroll"),...pointer,delta:z.number().int().min(-5).max(5).refine(n=>n!==0)}).strict(),
  z.object({operation:z.literal("type_text"),text:z.string().min(1).max(4096).refine(s=>!/[\u0000-\u001f\u007f]/.test(s))}).strict(),
  z.object({operation:z.literal("key"),key:z.enum(keys),modifiers:z.array(z.enum(["primary","alt","shift"])).max(3).default([])}).strict(),
]);
export function checkedImage(frame:z.infer<typeof frameSchema>) {
  const bytes=Buffer.from(frame.data,"base64");
  if(bytes.length>393_216||bytes.toString("base64")!==frame.data||bytes[0]!==0xff||bytes[1]!==0xd8||bytes.at(-2)!==0xff||bytes.at(-1)!==0xd9)
    fail("INVALID_FRAME","Native image is malformed or exceeds capture limits");
  return {data:frame.data,mimeType:frame.mimeType};
}
