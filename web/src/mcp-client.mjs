import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { ElicitRequestSchema } from '@modelcontextprotocol/sdk/types.js';

// Same-origin proxy (web/app.py) forwards /mcp to the MCP server (127.0.0.1:8765).
const MCP_URL = new URL('/mcp', (typeof window !== 'undefined' && window.location && window.location.origin)
  ? window.location.origin
  : 'http://127.0.0.1:8080');

export const DEMO_TOKENS = [
  { token: 'tok-manager', name: 'Facility Manager', role: 'manager' },
  { token: 'tok-chen', name: 'Chen (Researcher A+B)', role: 'researcher' },
  { token: 'tok-wang', name: 'Wang (Researcher A)', role: 'researcher' },
  { token: 'tok-li', name: 'Li (Researcher B)', role: 'researcher' },
];

export async function createSession(token, { onElicit, onLog } = {}) {
  const transport = new StreamableHTTPClientTransport(MCP_URL, {
    requestInit: { headers: { authorization: `Bearer ${token}` } },
  });
  transport.onmessage = (msg) => {
    if (onLog && msg && msg.method) {
      const m = typeof msg.method === 'string' ? msg.method : String(msg.method);
      onLog({ direction: 'in', method: m, status: '' });
    }
  };
  const client = new Client({ name: 'ser-web-client', version: '1.0.0' }, {
    capabilities: { elicitation: {} },
  });
  client.setRequestHandler(ElicitRequestSchema, async (req) => {
    const params = req.params ?? {};
    if (onLog) onLog({ direction: 'in', method: 'elicitation/create' });
    if (params.mode === 'url') {
      window.open(params.url, '_blank');
      if (onLog) onLog({ direction: 'out', method: 'elicitation/create', note: 'url-mode declined' });
      return { action: 'decline' };
    }
    const answer = onElicit
      ? await onElicit({ message: params.message ?? '', requestedSchema: params.requestedSchema ?? {} })
      : { confirmed: false };
    const action = answer && answer.confirmed === true ? 'accept' : 'decline';
    const result = action === 'accept' ? { action, content: { confirm: true } } : { action };
    if (onLog) onLog({ direction: 'out', method: 'elicitation/create', note: action });
    return result;
  });
  await client.connect(transport);
  return client;
}

export async function callTool(client, name, args = {}, { onLog } = {}) {
  if (onLog) onLog({ direction: 'out', method: 'tools/call', note: name });
  const res = await client.callTool({ name, arguments: args });
  const structured = res.structuredContent ?? null;
  if (onLog) {
    const status = structured && structured.status ? structured.status : (res.isError ? 'isError' : 'ok');
    onLog({ direction: 'in', method: `tools/call:${name}`, note: status });
  }
  return structured;
}

export async function closeSession(client) {
  try { await client.close(); } catch { /* ignore */ }
}
