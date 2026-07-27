import { RELEASE } from '../site.config';

/**
 * One launcher, rendered in each client's native configuration shape.
 *
 * Keep the package version pinned. A manually configured MCP server does not
 * inherit marketplace updates, and uv may reuse a cached unpinned resolution.
 */
export const mcpLaunch = {
  command: 'uv',
  args: [
    'tool',
    'run',
    '--quiet',
    '--no-progress',
    '--color',
    'never',
    '--no-config',
    '--isolated',
    '--from',
    `glyphpact[mcp]==${RELEASE.version}`,
    'glyphpact-mcp',
  ],
} as const;

export const mcpShellLauncher = [
  mcpLaunch.command,
  ...mcpLaunch.args.map((argument) =>
    argument.includes('[') ? `'${argument}'` : argument,
  ),
].join(' ');

const mcpServersConfig = (includeType = false) =>
  JSON.stringify(
    {
      mcpServers: {
        glyphpact: {
          ...(includeType ? { type: 'stdio' } : {}),
          command: mcpLaunch.command,
          args: mcpLaunch.args,
        },
      },
    },
    null,
    2,
  );

const vscodeConfig = JSON.stringify(
  {
    servers: {
      glyphpact: {
        type: 'stdio',
        command: mcpLaunch.command,
        args: mcpLaunch.args,
      },
    },
  },
  null,
  2,
);

const zedConfig = JSON.stringify(
  {
    context_servers: {
      glyphpact: {
        command: mcpLaunch.command,
        args: mcpLaunch.args,
      },
    },
  },
  null,
  2,
);

const tomlArguments = mcpLaunch.args
  .map((argument) => JSON.stringify(argument))
  .join(', ');

export const pluginInstall = {
  claude: `claude plugin marketplace add omar-hanafy/glyphpact
claude plugin install glyphpact@glyphpact`,
  codex: `codex plugin marketplace add omar-hanafy/glyphpact
codex plugin add glyphpact@glyphpact`,
} as const;

export interface McpClient {
  id: string;
  name: string;
  surface: string;
  location: string;
  codeTitle: string;
  code: string;
  instructions: string[];
  docs: string;
  docsLabel: string;
}

export const mcpClients: McpClient[] = [
  {
    id: 'antigravity',
    name: 'Antigravity / Agy',
    surface: 'Global or workspace JSON',
    location: '~/.gemini/config/mcp_config.json or .agents/mcp_config.json',
    codeTitle: 'mcp_config.json',
    code: mcpServersConfig(),
    instructions: [
      'Open MCP Servers, choose Manage MCP Servers, then View raw config.',
      'Merge the glyphpact entry into the existing mcpServers object. Do not replace unrelated servers.',
      'Use Refresh in the IDE. In Agy CLI, open /mcp and reload the server.',
    ],
    docs: 'https://antigravity.google/docs/mcp',
    docsLabel: 'Antigravity MCP documentation',
  },
  {
    id: 'cursor',
    name: 'Cursor',
    surface: 'Global or project JSON',
    location: '~/.cursor/mcp.json or .cursor/mcp.json',
    codeTitle: 'mcp.json',
    code: mcpServersConfig(true),
    instructions: [
      'Open Customize, select MCPs, and use the global or project configuration.',
      'Merge the glyphpact entry into mcpServers. Cursor requires type: stdio for this local process.',
      'Save the file, restart Cursor, and confirm that GlyphPact is enabled in the MCP list.',
    ],
    docs: 'https://cursor.com/docs/mcp',
    docsLabel: 'Cursor MCP documentation',
  },
  {
    id: 'jetbrains',
    name: 'JetBrains AI Assistant',
    surface: 'IDE settings',
    location: 'Settings > Tools > AI Assistant > Model Context Protocol',
    codeTitle: 'STDIO JSON configuration',
    code: mcpServersConfig(),
    instructions: [
      'Choose Add, select STDIO, and paste the JSON configuration.',
      'Choose whether the server belongs to this project or every project. Working directory is a separate field.',
      'Select OK, then Apply. The Status column shows when the server is connected.',
    ],
    docs: 'https://www.jetbrains.com/help/ai-assistant/mcp.html',
    docsLabel: 'JetBrains AI Assistant MCP documentation',
  },
  {
    id: 'vscode',
    name: 'VS Code / GitHub Copilot',
    surface: 'User or workspace JSON',
    location: 'MCP: Open User Configuration or .vscode/mcp.json',
    codeTitle: 'mcp.json',
    code: vscodeConfig,
    instructions: [
      'Run MCP: Open User Configuration, or add the file under .vscode for one workspace.',
      'Merge the glyphpact entry into the top-level servers object. VS Code does not use mcpServers.',
      'Run MCP: List Servers to start, restart, inspect output, and confirm the connection.',
    ],
    docs: 'https://code.visualstudio.com/docs/agent-customization/mcp-servers',
    docsLabel: 'VS Code MCP server documentation',
  },
  {
    id: 'zed',
    name: 'Zed',
    surface: 'Agent settings',
    location: 'Settings > AI > MCP Servers',
    codeTitle: 'Zed settings JSON',
    code: zedConfig,
    instructions: [
      'Choose Add Server, then Add Local Server, or open the raw settings file.',
      'Merge the glyphpact entry into context_servers. Zed uses this key instead of mcpServers.',
      'Return to MCP Servers and confirm that the status indicator is green.',
    ],
    docs: 'https://zed.dev/docs/ai/mcp',
    docsLabel: 'Zed MCP documentation',
  },
  {
    id: 'windsurf',
    name: 'Windsurf / Devin Desktop',
    surface: 'User JSON',
    location: '~/.codeium/windsurf/mcp_config.json',
    codeTitle: 'mcp_config.json',
    code: mcpServersConfig(),
    instructions: [
      'Open the MCPs panel in Cascade, or open Cascade > MCP Servers in Settings.',
      'Merge the glyphpact entry into mcpServers and save the configuration.',
      'Reopen the MCP panel and confirm that GlyphPact is connected.',
    ],
    docs: 'https://docs.devin.ai/desktop/cascade/mcp',
    docsLabel: 'Windsurf and Devin Desktop MCP documentation',
  },
  {
    id: 'gemini-cli',
    name: 'Gemini CLI',
    surface: 'User or project JSON',
    location: '~/.gemini/settings.json or .gemini/settings.json',
    codeTitle: 'settings.json',
    code: mcpServersConfig(),
    instructions: [
      'Choose user scope for every project, or project scope for one trusted repository.',
      'Merge the glyphpact entry into mcpServers and save the file.',
      'Run /mcp reload, then gemini mcp list to check the connection.',
    ],
    docs: 'https://geminicli.com/docs/tools/mcp-server/',
    docsLabel: 'Gemini CLI MCP documentation',
  },
  {
    id: 'claude-code',
    name: 'Claude Code, manual MCP',
    surface: 'User-scoped CLI',
    location: 'Claude Code user configuration',
    codeTitle: 'terminal',
    code: `claude mcp add-json --scope user glyphpact '${JSON.stringify({
      type: 'stdio',
      command: mcpLaunch.command,
      args: mcpLaunch.args,
    })}'`,
    instructions: [
      'Use this only when you want the MCP server without the GlyphPact plugin skill.',
      'Run claude mcp get glyphpact or open /mcp to confirm the registered server.',
      'Start a new Claude Code session after adding the manual configuration.',
    ],
    docs: 'https://code.claude.com/docs/en/mcp',
    docsLabel: 'Claude Code MCP documentation',
  },
  {
    id: 'codex-manual',
    name: 'Codex, manual MCP',
    surface: 'CLI or TOML',
    location: '~/.codex/config.toml or a trusted project .codex/config.toml',
    codeTitle: 'config.toml',
    code: `[mcp_servers.glyphpact]
command = ${JSON.stringify(mcpLaunch.command)}
args = [${tomlArguments}]`,
    instructions: [
      `The CLI equivalent is: codex mcp add glyphpact -- ${mcpShellLauncher}`,
      'Use this only when you want the MCP server without the GlyphPact plugin skill.',
      'Run codex mcp list or open /mcp, then start a new Codex session.',
    ],
    docs: 'https://learn.chatgpt.com/docs/extend/mcp',
    docsLabel: 'Codex MCP documentation',
  },
  {
    id: 'generic',
    name: 'Other stdio MCP clients',
    surface: 'Generic JSON',
    location: 'Your client\'s local MCP configuration',
    codeTitle: 'generic mcpServers entry',
    code: mcpServersConfig(),
    instructions: [
      'Use this shape when your client documents a top-level mcpServers object and local stdio servers.',
      'If the client requires a type field, add "type": "stdio" beside command.',
      'Restart or reload the client, then confirm the four GlyphPact tools before running a build.',
    ],
    docs: 'https://modelcontextprotocol.io/specification/2025-11-25/basic/transports',
    docsLabel: 'MCP transport specification',
  },
];

export interface McpToolDoc {
  name: string;
  boundary: string;
  className: string;
  purpose: string;
  inputs: string;
  returns: string;
  note?: string;
}

export const mcpToolDocs: McpToolDoc[] = [
  {
    name: 'audit_icon_pack',
    boundary: 'read only',
    className: 'gp-state-locked',
    purpose:
      'Compile one SVG, a directory, or a config into disposable storage. Review fidelity and safety findings before project files change.',
    inputs:
      'Exactly one absolute input_path or config_path. Policies default to lossy="error" and unrepresentable="error". Pages use offset and limit.',
    returns:
      'A structured audit summary, a bounded findings page, and a stable snapshot ID when findings exist.',
    note:
      'Page the same snapshot with snapshot_id, then release it with release_snapshot=true. Do not rerun the audit for each page.',
  },
  {
    name: 'build_icon_font',
    boundary: 'publishes',
    className: 'gp-state-lossy',
    purpose:
      'Build and transactionally publish the artifacts declared by an existing GlyphPact config.',
    inputs:
      'An absolute config_path. adopt_output is false unless the user explicitly approves replacing a non-empty unowned directory.',
    returns:
      'The schema-validated CLI result, artifact paths on success, and a bounded first page of build findings.',
    note:
      'A failed build without a published report can omit findings after the first 100. Fix the named failures and rerun instead of assuming the list was complete.',
  },
  {
    name: 'check_icon_font',
    boundary: 'coordination write',
    className: 'gp-state-ok',
    purpose:
      'Rebuild a candidate and compare it with committed output without rewriting the generated artifact set.',
    inputs: 'An absolute config_path. The default timeout is 600 seconds.',
    returns:
      'Success when output is current, or state="stale" and exitCode=3 when generated files drift.',
    note:
      'Check may create the output parent and leaves the persistent sibling coordination lock, so it is non-destructive but not read only.',
  },
  {
    name: 'read_icon_report',
    boundary: 'read only',
    className: 'gp-state-locked',
    purpose:
      'Validate and page a published iconfont.report.json without placing the entire report in the agent context.',
    inputs:
      'An absolute report_path, optional lossy or unrepresentable classification, and an offset and limit up to 500.',
    returns:
      'A report summary including remaining codepoints and range utilization, plus independently bounded pages for issues, glyphs, and skipped icons.',
  },
];

export const mcpResourceDocs = [
  {
    uri: 'glyphpact://schema/config',
    description: 'JSON Schema for icon-font configuration files.',
  },
  {
    uri: 'glyphpact://schema/report',
    description: 'JSON Schema for published iconfont.report.json files.',
  },
  {
    uri: 'glyphpact://schema/cli-result',
    description: 'JSON Schema for the inner GlyphPact CLI build and check result.',
  },
] as const;

export const mcpPrompts = {
  audit: `Audit the SVG icon pack at /absolute/path/to/icons with GlyphPact.
Keep lossy and unrepresentable policies strict.
Page every audit finding from the returned snapshot, summarize them by classification,
then release the snapshot. Do not change project files.`,
  build: `Use the GlyphPact config at /absolute/path/to/icon_font.json.
Audit it first. Ask before allowing any approximation or omission.
If the audit is accepted, build the font, run check_icon_font,
then summarize the published report.`,
  inspect: `Read /absolute/path/to/generated/iconfont.report.json with GlyphPact.
Page the issues, glyphs, and skipped icons. Report counts, policy,
approximations, omissions, and the generated font and Dart paths.`,
} as const;
