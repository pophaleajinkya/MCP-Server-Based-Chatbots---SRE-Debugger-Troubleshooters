import { NextResponse } from "next/server";
import { loadAgents } from "@/lib/agents";

export function GET() {
  const agents = loadAgents();
  return NextResponse.json({ agents });
}
