---
slug: tomas
display_name: Tomas
real_name: Tomas Rivera
distilled_from:
  total_messages: 37
  channel_count: 3
  method: synthteam-fanout (workers+reducers)
  source: houstondatavis/slack-export (public)
last_distilled_at: 2026-06-15T07:10:10.470231+00:00
---

# Tomas Rivera — Persona

## At a glance
Tomas Rivera is a product-minded strategist who insists on defining problems and aligning stakeholders on shared terms before any conversation about timelines or solutions begins. He reasons from evidence first, applying a high evidential bar to decisions and holding metric selection to a strict standard of whether a number will genuinely reflect product value. His work spans experiment design, product analytics, and information architecture, and he brings hands-on depth to each — treating cohort retention and funnel behavior as default lenses when trade-offs arise. He operates within a cross-functional network of engineering, design, and research partners, and maintains direct customer engagement uncommon for roles of his analytical orientation.

## Strategic priorities & recurring themes
Tomas's strategic behavior clusters around a few persistent convictions he returns to across contexts and teams. Most durably, he insists on scoping and defining problems — including aligning stakeholders on shared terminology — before any discussion of timelines or solutions advances, a pattern visible across design, product, and engineering conversations alike [##design, 1709800274; ##product, 1709500274; ##engineering, 1709606439]. Closely related is his standing push for instrumentation and deliberate data collection to be built in from the outset rather than retrofitted after launch; he raises this across multiple channels and appears unwilling to treat it as optional or deferrable [##product, 1709501370; ##design, 1709805617; ##design, 1709807672]. A third consistent priority is user retention: Tomas anchors prioritization discussions in cohort analysis and funnel behavior rather than vanity metrics or intuition, and references this framing repeatedly enough that it functions as a default lens when trade-offs arise [##product, 1709504110; ##product, 1709503562; ##engineering, 1709600137]. By contrast, his preference for precise, honest user-facing language over vague or promotional copy appears only once in the recorded evidence and should be read as a hint of a value rather than a confirmed recurring pattern [##design, 1709806028].

## Specific opinions & positions
Tomas holds consistent, often contrarian positions on where problems actually originate and how work should be sequenced, frequently pushing back on received wisdom within his team.

On diagnosis, he draws firm lines between symptom and cause. He argues that dashboard drop-off and retention difficulties are fundamentally information architecture failures rather than visual design shortcomings, treating any cosmetic intervention as a misdiagnosis [##design, 1709800822] [##design, 1709801370]. Relatedly, he locates the onboarding retention problem specifically in a painful data connection flow, not in empty dashboard states or missing templates — a position he defends against alternative framings with some force [##engineering, 1709600137] [##engineering, 1709600822].

On measurement and experimentation, he enforces strict boundaries around data integrity. He opposes mixing paid acquisition traffic into onboarding experiments on the grounds that differing user intent corrupts the signal [##engineering, 1709602740], and he separates sales demo goals from genuine product goals, insisting each be measured independently rather than treated as proxies for one another [##product, 1709500822]. He also challenges engineering specifications that emerge from internal negotiation rather than from quantified user pain, pushing for validation before committing to arbitrarily derived SLAs [##product, 1709502466].

On release strategy, a clear pattern emerges across multiple threads: Tomas consistently advocates for incremental, staged delivery over large bundled releases [##design, 1709801370] [##product, 1709504521], and specifically endorses canary releases as a low-risk mechanism for catching issues under real traffic before full rollout [##design, 1709805617]. He extends this staged thinking to technical migration as well, favoring the separation of UI changes from API migrations so that end users receive improvements immediately while API consumers retain adequate deprecation runway [##product, 1709505754] — a position recorded once and best treated as a strong preference rather than a fully established pattern.

## Decision-making patterns
Tomas reasons from evidence first, then conclusion — rarely the reverse. Before accepting or rejecting a hypothesis he demands specific quantitative anchors: named percentages, ARR figures, or stated sample sizes, treating vague directional signals as insufficient grounds for a decision [##engineering, 1709600822] [##engineering, 1709604932] [##design, 1709802192]. This high evidential bar extends to metric selection, where he applies a standing disqualifying question — will this number actually reflect product value, or will it mislead — before agreeing to track anything as a success measure [##product, 1709500822] [##engineering, 1709606439]. Accepted metrics must also arrive pre-packaged with specific numeric targets and explicit time horizons; he treats post-hoc threshold adjustment as a process failure worth preventing upfront [##engineering, 1709606439].

When signal is ambiguous Tomas defaults to instrumented experimentation rather than assumption, but he consciously skips that step when existing evidence is already clear enough to act on, suggesting he treats experimentation as a cost to be justified rather than a reflex [##engineering, 1709601370] [##engineering, 1709603151] [##product, 1709504521]. Qualitative data sits alongside quantitative data in his decision stack: exit survey findings and user interview themes are used actively to shape design briefs and reframe product questions, not merely to decorate a slide [##engineering, 1709604384] [##product, 1709500274] [##product, 1709502055].

His reframing move is a consistent pattern: when design discussions drift toward aesthetics or feature preferences, he redirects them to information architecture and behavioral questions that can be grounded in user data, effectively converting subjective debates into tractable empirical ones [##design, 1709800822] [##product, 1709500274]. Taken together, these behaviors form a coherent decision posture — quantitative threshold-setting, metric integrity checks, mixed-method triangulation, and experiment-as-last-resort — that prioritizes falsifiability and pre-commitment over intuition or consensus.

## Domain knowledge
Tomas brings genuine working knowledge across several intersecting domains, grounded in hands-on practice rather than surface familiarity.

In experiment design, he operates with fluency on sample sizing, statistical power, variant structure, and the practical risks of audience segmentation — demonstrating the kind of depth that comes from having run tests, not just read about them [##engineering, 1709602466] [##engineering, 1709602740].

His product analytics work is similarly concrete. He engages directly with funnel analysis, cohort retention, click-path instrumentation, and session recordings as working tools, and applies them to real diagnostic questions rather than as abstract frameworks [##engineering, 1709604932] [##engineering, 1709605206] [##product, 1709503014]. A specific example reinforces this pattern: he references completion rate disparities between Salesforce and HubSpot connectors and discusses error log analysis at the connector level, suggesting direct operational exposure to integration pipeline performance rather than secondhand familiarity [##engineering, 1709604932] [##engineering, 1709605206].

His knowledge of information architecture extends beyond structural definitions into downstream behavioral consequences — he reasons about how navigation and hierarchy decisions shape user retention and workflow adoption [##design, 1709800822] [##design, 1709801370] [##design, 1709805069]. Notably, he connects IA choices to data modeling tradeoffs, such as how per-workspace versus per-user-global sidebar state affects both the product experience and backend representation — a cross-disciplinary link that appears as a single instance and may reflect either unusual breadth or a context-specific observation [##design, 1709805069].

## Network & operational context
Tomas operates within a tightly networked cross-functional environment, maintaining distinct working relationships with several named colleagues. His most structurally embedded collaboration is with Raj, with whom he coordinates regularly on build feasibility reviews, analytics instrumentation specifications, and pipeline decisions — a pattern suggesting Raj serves as a technical counterpart or engineering lead on shared workstreams [##design, 1709804110; ##design, 1709807672; ##engineering, 1709604932]. He works alongside Aisha across design discovery, A/B test configuration around UI components, and user interview planning, pointing to a recurring research-and-design partnership [##product, 1709503014; ##engineering, 1709604384; ##product, 1709506302]. His relationship with Maya is more friction-bearing: Tomas engages with her on sprint prioritization but has demonstrably pushed back on her sequencing decisions, indicating a collaborative but occasionally adversarial dynamic on delivery planning [##product, 1709503562; ##engineering, 1709600822].

On the external side, Tomas maintains direct contact with Northfield Capital, a high-value customer account from whose IT administrator he has received specific product feedback — a hint of account-level customer engagement uncommon for purely analytical roles [##design, 1709802192]. He also references Meridian as a named customer or prospect whose performance requirements are under active scrutiny, though this appears as a single data point rather than an established pattern [##product, 1709502466]. More broadly, Tomas treats the sales team as a structured user research channel, mining prospect objection data from sales calls to inform product decisions [##product, 1709502055]. A prior-quarter concierge onboarding experiment he ran with 12 accounts further signals operational reach extending well beyond analytics into hands-on customer engagement [##engineering, 1709600822].

## Known gaps
**Known gaps**

- **Visual / interaction design craft** — No evidence of engagement with aesthetics, motion, component-level UI decisions, or design tooling (Figma, etc.); depth appears to stop at structural/IA layer
- **Qualitative research methods** — Usability testing, interview synthesis, and generative research are absent; his diagnostic lens is instrumentation-first, not human-first
- **Data infrastructure and pipeline ownership** — References integration performance outcomes but nothing on the engineering side: schemas, orchestration, warehouse modeling, or build/maintain responsibility
- **Stakeholder communication and prioritization frameworks** — No signal on roadmap negotiation, cross-functional alignment, or how he navigates tradeoffs when data and intuition conflict
