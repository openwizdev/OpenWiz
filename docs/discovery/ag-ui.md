# AG-UI and A2UI for the generative-UI grill

AG-UI carries an agent run between an application and a backend. A2UI describes a UI the application can render. The A2UI spec describes AG-UI as one possible transport binding. The grill can compare a native display, a shared component format, and a shared agent connection as separate choices. [AG-UI specification][ag-spec], [A2UI transport contract][a2-spec], [RX5][rx5].

## Sources and maintenance

- **AG-UI** is maintained in [ag-ui-protocol/ag-ui][ag-repo]. I read [`96caee88f5e441d4901d626b5d199a3e9de7c667`](https://github.com/ag-ui-protocol/ag-ui/commit/96caee88f5e441d4901d626b5d199a3e9de7c667), the 2026-11-27 release merge. Its root licence is [MIT](https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/LICENSE). The repository has separate 1.0 and draft spec tracks, and the 1.0 change notes explain how it differs from 0.x. The spec track gives a version to target. Package and bridge compatibility for a specific Wiz configuration is unverified. [Spec tracks][ag-tracks], [1.0 changes][ag-changes].
- **A2UI** is maintained in [a2ui-project/a2ui][a2-repo], the repository the [original Google URL][a2-original] redirects to. I read [`36725eee042da90c526f469f94246f96e16fdc35`](https://github.com/a2ui-project/a2ui/commit/36725eee042da90c526f469f94246f96e16fdc35), dated 2026-11-25. Its root licence is [Apache-2.0](https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/LICENSE). Upstream marks the 1.0 spec stable. Its SDK table lists versions by package, including older wire versions. These are public maintenance signals. Long-term support commitments and the licence of every optional adapter, renderer, or custom catalog are unverified. [Version 1.0][a2-version], [SDK matrix][a2-sdks].

## What a client implements

### AG-UI

The application sends `RunAgentInput` to start an exchange, with conversation and run IDs, messages, state, and tools as described in the schema. The producer returns an ordered stream. Run lifecycle events are required. Other event families include streamed text, tool calls and results, reasoning, state and message snapshots, activity, subagent lifecycle, and raw or custom events. A state snapshot replaces the state and a state delta applies an RFC 6902 JSON Patch. [Run input][ag-input], [Event families][ag-events], [State events][ag-state].

A client needs a transport decoder, protocol validation and version handling, run and message state, and a view that renders the parts it supports. The JavaScript HTTP client sends a request and decodes an SSE stream. The processing rules distinguish unknown material from malformed known events. The application decides which frontend tools or app-specific actions to expose and render. `CUSTOM` allows an agreed payload but supplies no common card, chart, or form catalog. Transporting data in a custom event still leaves the rendering and action map to the host. [HTTP client][ag-http], [Processing][ag-processing], [Custom events][ag-custom], [Tool calls][ag-tools].

### A2UI

A2UI 1.0 exchanges versioned JSON envelopes. `createSurface` starts a surface, `updateComponents` defines or updates components by ID, `updateDataModel` changes the values they bind to, and `deleteSurface` removes it. Components are selected from an agreed catalog and linked into a tree. Renderers can send user actions, errors and function responses. The transport supplies framing, capability metadata and the exchange with the agent. A2UI leaves the conversation and agent run to the hosting application. [Wire protocol][a2-spec], [Renderer messages][a2-up], [Agent SDK][a2-sdks].

A client needs a processor for surface and data state, validation for the agreed catalog and version, native component mappings, and an action return path. The Basic Catalog covers cards and form controls. A chart such as VegaChart needs a catalog and renderer that support it. Renderers can register functions. The application still sets which functions exist, handles confirmation and permissions, and must validate actions at its own effect boundary. A schema describes valid data, while authorization is an application decision. [Basic Catalog][a2-basic], [VegaChart catalog][a2-chart], [Protocol functions][a2-spec], [Catalogs][a2-catalogs].

## Where the UI would render

**T3 Code today.** The Wiz home spec places the chat in a pinned T3 thread. At [T3 Code `71a5e97ce239257eb1116b811fa577af1bfd594b`](https://github.com/pingdotgg/t3code/commit/71a5e97ce239257eb1116b811fa577af1bfd594b), the web transcript routes assistant messages to its own timeline row and has a Markdown renderer. The public README documents several provider harnesses and clients. **Unverified:** a supported extension that lets Wiz inject arbitrary reply components into this timeline, built-in AG-UI or A2UI support in that path, and parity for generated cards across desktop, web, and phone. [Wiz home][home], [T3 timeline][t3-timeline], [T3 Markdown][t3-markdown], [T3 README][t3-readme].

**WizBar today and in its plan.** The public WizBar spec uses one board core and the same files across T3, CloudRoom, VS Code or Cursor, and a local web view. It assigns writes to the T3 board through its existing guarded routes and to Wiz in chat. The other surfaces stay read-only. That boundary applies even when a card is generated. The rows below are integration estimates from the cited interfaces. [WizBar spec][bar], [Feed spec][feed].

| Surface | T3-native | AG-UI | A2UI |
| --- | --- | --- | --- |
| Wiz replies in T3 Code | Start with Markdown or links. For interactive cards, add a typed attachment to T3’s own transcript and render an approved set of native views. This would need a supported host change or extension and a text fallback for clients that cannot render it. [T3 timeline][t3-timeline], [T3 Markdown][t3-markdown]. | Bridge the T3 provider or chat events to an AG-UI producer, map run identity, tools, lifecycle and state, then wire a consumer to the transcript. Add the card renderer separately. The bridge earns its cost if a second agent client needs the same stream. [AG-UI specification][ag-spec], [Run input][ag-input], [Custom events][ag-custom]. | Put a renderer beside the existing transcript, carry A2UI envelopes over a supported channel, retain surface state with the reply, agree on a catalog, and route actions through existing permission checks. Web and native clients need compatible renderers or a text fallback. [A2UI wire protocol][a2-spec], [SDK matrix][a2-sdks], [Wiz home][home]. |
| WizBar cards | Keep typed board view models and fixed shared cards when the data is already in the feed. T3 can render its own cards while other hosts render the shared models and keep their read-only behaviour. [WizBar spec][bar], [Feed spec][feed]. | The board would need a producer and consumer for a live agent run and a mapping from activity or custom events to a card. The existing files and board view models cover the fixed-board case without streaming a second copy of agent state. [Activity events][ag-activity], [Custom events][ag-custom], [WizBar spec][bar]. | Translate a view model or an approved agent response into a small shared catalog. Each host needs a renderer or a fallback and should expose only the actions it is allowed to perform. Conformance would need to cover the same visible cards and the same absence of writes on read-only hosts. [A2UI catalogs][a2-catalogs], [SDK matrix][a2-sdks], [WizBar spec][bar]. |

The grill can ask whether the first card needs live run state, whether the same generated layout must render in two distinct hosts, and which actions the owner would allow. The first question is evidence for AG-UI, the second for A2UI, and the last is a host permission decision in either design. [AG-UI state][ag-state], [A2UI catalogs][a2-catalogs], [WizBar spec][bar].

## Documented emitters

- **AG-UI:** Upstream documents bridges for the Claude Agent SDK and the Google Antigravity SDK, and lists LangGraph, Google ADK, Microsoft Agent Framework, AWS Strands, Mastra, Pydantic AI and the OpenAI Agents SDK among its framework integrations. CopilotKit appears on the client side. Unverified: emission by standalone Claude Code or Codex, and whether a bridge can reuse T3’s existing session. [Upstream integrations][ag-integrations], [Claude SDK bridge][ag-claude], [Antigravity SDK bridge][ag-anti], [T3 README][t3-readme].
- **A2UI:** The project documents its own TypeScript, Python and Dart agent SDKs and a Google ADK integration. Its agent guide also describes CopilotKit exposing an A2UI generation tool with adapters for Google ADK, LangGraph and AWS Strands. This is configured emission through an SDK or middleware. React, Lit, Angular, Flutter, SwiftUI and Jetpack Compose appear on the rendering side, which is a separate capability. Unverified: native A2UI emission from the stock coding harnesses used by Wiz, and 1.0 interoperability for every cited middleware path. [Agent and renderer SDKs][a2-sdks], [Agent integration guide][a2-agents], [T3 README][t3-readme].

## Verdict: no

**AG-UI** — For Wiz, decline adoption and a listing from this evidence. The protocol is permissively licensed and the adapters are concrete. The identified work is rendering replies and cards inside existing hosts. AG-UI adds a run transport and state mapping while leaving that rendering work to the host. There is no verified T3 path or independent client requirement that would justify the added integration or make it an installable Wiz choice today. [AG-UI specification][ag-spec], [Custom events][ag-custom], [Wiz home][home], [WizBar spec][bar].

**A2UI** — For Wiz, decline adoption and a listing from this evidence. A2UI is the closer fit if the grill asks for the same dynamic layout across hosts. It still needs a transport, catalogs, renderers, and host action wiring. The current WizBar plan shares fixed views and the T3 integration is unverified. Without an agreed generated surface and a supported renderer path, an opt-in listing does not give Wiz users working cards. [A2UI wire protocol][a2-spec], [SDK matrix][a2-sdks], [WizBar spec][bar], [RX5][rx5].

[ag-spec]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/index.mdx
[ag-repo]: https://github.com/ag-ui-protocol/ag-ui
[ag-tracks]: https://github.com/ag-ui-protocol/ag-ui/tree/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec
[ag-changes]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/changelog.mdx
[ag-input]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/basic/run-input.mdx
[ag-events]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/events/index.mdx
[ag-state]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/events/state.mdx
[ag-http]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/sdk/js/client/http-agent.mdx
[ag-processing]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/basic/processing.mdx
[ag-custom]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/events/passthrough.mdx
[ag-tools]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/events/tool-calls.mdx
[ag-activity]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/spec/1.0/events/activity.mdx
[ag-integrations]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/docs/integrations.mdx
[ag-claude]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/integrations/claude-agent-sdk/typescript/README.md
[ag-anti]: https://github.com/ag-ui-protocol/ag-ui/blob/96caee88f5e441d4901d626b5d199a3e9de7c667/integrations/antigravity/python/README.md
[a2-repo]: https://github.com/a2ui-project/a2ui
[a2-original]: https://github.com/google/A2UI
[a2-version]: https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/specification/v1_0/README.md
[a2-spec]: https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/specification/v1_0/docs/a2ui_protocol.md
[a2-up]: https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/specification/v1_0/json/renderer_to_agent.json
[a2-basic]: https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/catalogs/basic/v1/catalog.json
[a2-chart]: https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/catalogs/vegachart/v1/catalog.json
[a2-catalogs]: https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/docs/site/src/content/docs/concepts/catalogs.mdx
[a2-sdks]: https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/docs/site/src/content/docs/concepts/sdks.mdx
[a2-agents]: https://github.com/a2ui-project/a2ui/blob/36725eee042da90c526f469f94246f96e16fdc35/docs/site/src/content/docs/guides/agent-integration.mdx
[t3-readme]: https://github.com/pingdotgg/t3code/blob/71a5e97ce239257eb1116b811fa577af1bfd594b/README.md
[t3-timeline]: https://github.com/pingdotgg/t3code/blob/71a5e97ce239257eb1116b811fa577af1bfd594b/apps/web/src/components/chat/MessagesTimeline.tsx#L1744-L1747
[t3-markdown]: https://github.com/pingdotgg/t3code/blob/71a5e97ce239257eb1116b811fa577af1bfd594b/apps/web/src/components/ChatMarkdown.tsx
[rx5]: https://github.com/openwizdev/OpenWiz/issues/3708
[home]: https://github.com/openwizdev/OpenWiz/issues/3432
[bar]: https://github.com/openwizdev/OpenWiz/issues/3467
[feed]: https://github.com/openwizdev/OpenWiz/issues/3409
