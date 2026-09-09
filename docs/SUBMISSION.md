# Submission checklist

**Hard deadline: Sep 14, 2026 @ 5:00pm PDT.**
Source: <https://agentsforhumans.devpost.com/rules>

## Do these first (they gate everything else)

- [ ] **Register on Devpost** — <https://agentsforhumans.devpost.com/> ("Join hackathon")
- [ ] **Request $50 AWS credits — DEADLINE Sep 11 @ 12:00pm PT**
      <https://forms.gle/6sjzKiX6bKUMA5NEA>
      (Must be registered for the hackathon first. Credits expire Oct 31.)
- [ ] **Create an AWS Builder ID** — required field on the submission form
- [ ] **Enable Bedrock model access** for Claude Sonnet in your region
      <https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html>

## Required submission artifacts

- [ ] Text description: what it does, who it's for, how it works
- [ ] **PUBLIC** repo URL
- [ ] All source code, assets, and setup instructions needed to run it
- [ ] MIT or Apache license, **visible in the repo's About section** (GitHub sidebar)
- [ ] README
- [ ] Architecture diagram
- [ ] Demo video, **max 5 minutes**, that:
  - [ ] demonstrates the working project end to end
  - [ ] covers (1) the problem, (2) who it's for, (3) why it matters
  - [ ] slides / screen recording / voiceover all fine — no need to be on camera
  - [ ] uploaded to YouTube or Vimeo, **public**
- [ ] AWS Builder ID
- [ ] Track selected: Everyday / Professional / Good Neighbor

## Score boosters (optional, but cheap points)

- [ ] **Live demo link** — explicitly scores higher on Technical Implementation
- [ ] **Deploy with Amazon Bedrock AgentCore** — explicitly strengthens Technical Implementation
- [ ] **builder.aws.com blog post(s)** — see the dedicated section below. Worth up
      to **+0.6**, scored **0.2 per post**, so **three posts** maxes it out.

## builder.aws blog post bonus (worth up to +0.6)

Source: Official Rules, sections 5 and 6.

**The scoring maths — this is the part that matters:**

- **0.2 points per piece of content**, capped at **+0.6 total**.
- So **three separate posts** is the maximum, not one long one. Plan three.
- Base scores run 1–5, so the bonus lifts the ceiling to **5.6**. In a field where
  the top entries cluster, 0.6 is a large margin.

**Requirements:**

- [ ] Published **publicly** on <https://builder.aws.com> (nowhere else counts)
- [ ] Covers **your journey building and implementing AWS** for this hackathon
- [ ] Uses **"Agents for Humans" in the title**
- [ ] Published **before the submission deadline** (Sep 14, 5:00pm PDT)

**Two caveats worth knowing:**

1. **Only submissions that advance to Stage Two earn the bonus.** The post cannot
   rescue a weak project — it is a multiplier on work that already scored well.
   Build first, write second.
2. **Hashtag vs. plain phrase.** The rules header states they were
   *"Updated 8/12/26 to remove requirement of #AgentsforHumans in Blog Post Bonus
   Submission items"*, but section 6 still reads *"Use hashtag Agents for Humans in
   the title."* The safe move that satisfies both readings: put the plain phrase
   **Agents for Humans** in the title.

**Three-post plan (0.2 each):**

- [ ] **Post 1 — the problem.** Who you built for and why it's worth automating.
      Write this early; it doubles as your Devpost description and video script.
- [ ] **Post 2 — the build.** Strands Agents architecture: your tools, the system
      prompt, where a human stays in the loop. Feed this from `docs/ARCHITECTURE.md`.
- [ ] **Post 3 — the deploy.** Bedrock model access, AgentCore, what broke and how
      you fixed it. Write-ups of real failures read as credible.

## Rules worth not tripping over

- **New projects only.** Must be created during the submission period. You may use
  frameworks, libraries, starter templates, and AI coding assistants, but you must
  **disclose any pre-existing code**.
- The project must actually install and run as depicted in the video.
- **Judges must be able to access and test it.** The rules require "a link to a
  website, functioning demo, or a test build", free of charge and unrestricted,
  until judging ends. If anything is behind a login, you must supply credentials in
  the testing instructions. A public repo with working setup instructions satisfies
  the "test build" reading, but a hosted demo is the safer and better-scoring option.
- Judges are **not obliged to run your code** — they may score on the description,
  images, and video alone. Which is why the video carries so much weight.
- One project can win only one prize.

## Judging criteria (weight your effort accordingly)

1. **Technical Implementation** — how thoroughly and skillfully it uses Strands
   Agents; non-trivial, genuinely working. Live demo and/or AgentCore strengthen this.
2. **Design** — a complete, coherent product experience, not a proof of concept.
3. **Potential Impact** — a credible, specific case for a real problem and audience.
4. **Creativity & Originality** — non-obvious use of Strands; real understanding
   of the problem space.
5. **Presentation** — video clearly shows it working end to end; pitch is easy to follow.
