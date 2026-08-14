# Fractal Desk v1 — delivery case study

**A university–industry partnership between Fractal Digital Solutions and
Universidad Nacional de Costa Rica (UNA).**

My role was client-side sponsor and general director on the Fractal side. I
owned requirements, scope, acceptance criteria and the delivery schedule. **I did
not write the code.** Five informatics students at UNA built the system, and the
implementation is theirs.

There is no code in this document, and no code from v1 appears anywhere in this
repository. See [Ownership](#ownership-and-what-this-document-is-not) at the end.

> **TODO placeholders.** Every `TODO(...)` below marks a number or date I have to
> fill in from my own records. They are deliberately blank rather than estimated.

---

## The problem

Fractal's clients — real estate agents and brokerages, construction firms,
hospitality operators and professional-services practices, mostly on the
Guanacaste coast — were running client work across three disconnected surfaces:

- **Email** for anything formal: proposals, contracts, invoices, approvals.
- **WhatsApp** for everything actually operational. Costa Rican business runs on
  WhatsApp, and that is where scope got agreed, changed, and forgotten.
- **Spreadsheets** for whatever needed a list: pipelines, project stages,
  billing schedules. Usually one spreadsheet per person, none of them agreeing.

Three consequences followed, and they compounded:

**Project status lived in people's heads.** There was no place you could look to
find out where a project actually stood. You asked someone. If they were on site,
travelling, or had left, the answer was unavailable — and in a small firm,
"unavailable" and "does not exist" are the same thing. Handover between staff
meant a conversation, and what did not come up in that conversation was lost.

**Invoicing was disconnected from delivery.** Work was completed in one system
(nowhere) and billed in another (an accountant's records). Nothing tied a
delivered milestone to an issued invoice. Work got delivered and not billed. Work
got billed that the client disputed because nobody could point to the
deliverable. The gap between doing the work and being paid for it was measured in
weeks of chasing.

**Electronic invoicing was a separate manual step.** Costa Rica has had mandatory
electronic invoicing since 2018, and every invoice has to be built to Hacienda's
XML format, cryptographically signed and transmitted. In practice this meant
re-keying details into a separate tool that knew nothing about the project the
work belonged to. Every re-key was an opportunity to get a number wrong, and
every correction was another document.

None of these is an unusual problem. That was part of the appeal as a student
project: the domain is real, the constraints are real, and the requirements are
discoverable by talking to actual users rather than invented.

---

## The engagement

A partnership between Fractal Digital Solutions and UNA, structured as a
university project with a real external client.

| | |
|---|---|
| **Client / sponsor** | Fractal Digital Solutions — me, as general director |
| **Delivery team** | Five informatics students at Universidad Nacional de Costa Rica |
| **My role** | Requirements, scope, acceptance criteria, schedule, dependency tracking, milestone review |
| **Their role** | Architecture, implementation, testing, deployment — all of it |
| **Duration** | TODO(project duration — start month/year to end month/year) |
| **Cadence** | TODO(how often milestone reviews happened — weekly? fortnightly?) |
| **Academic frame** | TODO(course / programme this sat inside, and how it was assessed) |

The arrangement was genuinely two-sided. The students needed a real client with
real requirements and a real deadline, which is difficult to simulate inside a
university. Fractal needed a system it could not have justified paying market
rate to build. Both sides got what they came for, which is not the usual outcome
for university–industry projects.

What made it work was that I behaved like a client and not like a lecturer. I
said what the business needed and what "done" meant, and I reviewed against
that. I did not tell them how to build it, and when I disagreed with a technical
decision I said so once and then deferred. Technical decisions were theirs. That
boundary was the single most important thing about the engagement, and I held it
deliberately.

---

## Scope of v1

Three modules, in dependency order.

### 1. CRM

Clients, contacts, and the pipeline from first conversation to signed work.

The requirement that shaped it: a client in this market is rarely one person. A
property deal involves an owner, an agent, sometimes a lawyer, sometimes a
relative abroad making the decision. The CRM had to model a client as a set of
people with different roles rather than as a single contact record, because
"who do I actually call about this" is the question people ask.

### 2. Project management

Projects, phases, deliverables, and status against a plan.

The requirement that shaped it: status had to be derivable rather than reported.
A field that someone updates by hand is a field that goes stale, and a stale
status field is worse than no status field because people trust it. Status came
from whether the deliverables under a phase were complete.

### 3. Electronic invoicing via GTI

Integration with **GTI**, a Costa Rican electronic-invoicing provider, so an
invoice could be raised from a completed project milestone and go out as a
compliant electronic document without re-keying.

This was the module that justified the whole project. The other two modules are
things you can buy. The connection between *delivery* and *the electronic
document that bills for it* is the thing that did not exist, and it was where the
money was leaking.

Using GTI rather than integrating with Hacienda directly was a scoping decision I
made early and would make again. Building the signing and transmission layer
directly means taking on cryptographic key custody, XAdES signing, schema
compliance and an asynchronous submission protocol — none of which is a student
project, all of which is a liability. A provider abstracts it behind an API.
The trade is a dependency and a per-document cost against not owning a
compliance surface. For a five-person team on a fixed academic calendar, that
trade was not close.

**Out of scope, explicitly:** accounting, payroll, and any kind of tax
declaration. The system produced invoices; it did not do the books.

---

## My role, stated precisely

I want to be exact about this, because the distinction matters and it is easy to
blur when describing a project you sponsored.

**What I owned:**

- **Requirements definition.** What the system had to do, expressed as user needs
  rather than features. This came from sitting with the people who would use it
  and from my own operational knowledge of the client work.
- **Scope.** What was in v1 and what was not. Including the decision to use a
  provider for invoicing rather than build the compliance layer.
- **Acceptance criteria.** What "done" meant for each module, written down before
  the module was built, in terms an assessor could check without me in the room.
- **Delivery schedule.** Milestone dates, sequenced against the academic
  calendar rather than against an ideal engineering order.
- **Dependency tracking.** Which pieces blocked which, and — mostly — which
  external dependencies (the GTI integration, credentials, client sign-off)
  needed to be unblocked by me before the team hit them.
- **Milestone review.** Reviewing delivered work against the criteria and
  deciding whether it passed.

**What I explicitly did not own, and did not do:**

- **The implementation.** All of it — architecture, data model, code, tests,
  deployment — was the student team's work. I did not write code for this
  project, and I did not direct how it was written.
- **Technical design decisions.** Stack, structure, libraries, patterns. Theirs.
- **Estimation.** They estimated their own work. I pushed on dates when a date
  mattered to the business, but I did not tell them how long something should
  take, because I was not the one doing it.

The clean version of the boundary: **I owned the "what" and the "when". They
owned the "how".** Where I was useful was in being decisive about the first two
so that the third was not blocked on me. Where I was not useful was the handful
of times I had an opinion about the "how" and voiced it — those conversations
cost time and improved nothing.

---

## How the work was run

### Agreeing scope

Scope was agreed up front, per module, in writing, before any module started. Not
a specification document — a statement of what the module had to let a user do
and what would be checked at the end.

The thing I did that mattered most was writing acceptance criteria **before**
the build rather than after. The obvious reason is that it stops scope drifting.
The real reason is different: writing down what "done" means forces you to
discover the requirements you have not thought about yet, while it is still cheap
to discover them. Several times I sat down to write acceptance criteria for
something I thought was well understood and found I could not, because a decision
had not actually been made. Better to find that at a desk than three weeks into
a build.

### Reviewing milestones

Milestone reviews were demo-based. Working software, driven by the team, against
the acceptance criteria agreed at the start of that module. Not a slide deck, not
a status report — the thing, running.

Two rules I held to:

1. **Review against the written criteria, not against what I felt like that day.**
   If I wanted something that was not in the criteria, that was a new request for
   the next milestone, not a failure of this one. A sponsor who moves the bar at
   review time destroys a team's ability to plan, and does it while feeling
   reasonable.
2. **Pass or fail, decided in the room.** Not "let me think about it." A team
   waiting on a sponsor's verdict is a team that cannot start the next thing.

Cadence: TODO(how often reviews happened).

### What changed mid-project, and how

Two changes mattered.

**The GTI integration was harder than scoped.** The gap between "there is an API"
and "the documents it produces are accepted, in every case the business actually
generates" was much wider than I allowed for. Credentials, environments, the
difference between a document the sandbox accepts and one production accepts, and
the error cases — a rejected document is a normal outcome that has to be handled,
not an exception. I had scoped it as an integration. It was closer to a
sub-project.

How it was handled: I cut scope elsewhere rather than moving the date. The
academic calendar was fixed and not negotiable, so the date was the one variable
that could not move. Reporting and some of the softer CRM features came out to
protect the invoicing integration, on the reasoning that the invoicing
integration was the reason the project existed and everything else was
replaceable with a spreadsheet.

That was the right call and I would make it again. What I would do differently is
have seen it coming — see below.

**Requirements I had not thought of surfaced during demos.** Every review turned
up something. That is what reviews are for, and I do not count it as a failure of
the requirements process. What I did wrong was, early on, letting those go into
the current milestone instead of the next one. It made the team's plan
meaningless. I stopped doing it partway through and started writing them down for
the next milestone instead — which is what should have happened from the first
review.

TODO(any other significant mid-project change — a team member leaving, a
dependency changing, a requirement being dropped?)

---

## Outcome

The system was delivered.

- **Modules delivered:** CRM, project management, and the GTI electronic
  invoicing integration.
- **Delivered on schedule:** yes — with scope reduced mid-project to protect the
  date, as described above.
- **Users:** TODO(how many people used the system)
- **Usage frequency:** TODO(daily? weekly? per-project?)
- **What it replaced:** TODO(what specifically stopped being used — which
  spreadsheets, which manual steps)
- **Time in production:** TODO(how long it ran before v2 became necessary)
- **Academic outcome:** TODO(how the project was assessed, and the result)

For the students, the outcome I care about is that they shipped something a real
business used, against a real deadline, for a client who said no to things. That
is not simulable, and it is most of the value of an engagement like this.

---

## What I would do differently

**1. I would have spiked the invoicing integration in week one.**

This is the big one. I scoped GTI as an integration and it behaved like a
sub-project, and I only learned that when the team hit it — by which point the
schedule was committed and the only lever left was cutting scope.

Two days of throwaway work at the start, purely to answer "can we get one
document through end to end, in a real environment, with real credentials",
would have told me the size of the thing while I still had every option open.
The lesson generalises past this project: **the part of a system that talks to
somebody else's system is the part you cannot estimate from the outside, so you
buy the information early rather than discovering it late.** Integration risk is
the only risk worth spending schedule on up front.

**2. I would have written acceptance criteria for the integration in terms of
failure cases, not the happy path.**

My criteria said an invoice could be raised from a milestone and transmitted
successfully. They said nothing about a rejected document, a timeout, a
duplicate, or a document the provider accepted but the tax authority later
did not. Those are not edge cases in electronic invoicing — they are Tuesday.
Because they were not in the criteria, they were not in the plan, and they became
work discovered during the build.

The general form: **for anything asynchronous or external, define done by what
happens when it goes wrong.** The happy path is the part everyone gets right
anyway.

**3. I would have separated "the sponsor wants this" from "this is a defect".**

Early on I raised both in the same conversation, in the same tone, at review
time. To a team, those are completely different things — one is new work, the
other is work not finished — and blurring them makes everything feel like
failure. I got better at this partway through. I should have started that way.

**4. I would have kept a written decision log.**

Scope decisions were made in conversation and I remembered the reasoning. The
team remembered the outcome. Two months later, when a decision was questioned,
nobody could reconstruct *why*, so it got relitigated. A dated list of decisions
and one line of reasoning each would have cost almost nothing.

**5. I would have been slower to volunteer opinions on implementation.**

Covered above. Every time I had a view on "how", it cost a conversation and
changed nothing. The value I added was entirely on the "what" and the "when".

---

## Why v2 exists

v1's invoicing module was built against Costa Rica's tax administration as it
existed at the time: the **ATV** platform, and the electronic-document format
versions in force then.

That ground moved completely.

- **1 September 2025** — electronic invoice format **version 4.4** became
  mandatory. Not a revision to the previous format. New required fields, a
  reworked tax breakdown, changes to how economic activity is declared, revised
  catalogues.
- **6 October 2025** — **TRIBU-CR** replaced ATV as the tax administration
  platform. Not a new front end on the same system — a different system, with a
  different data model and different obligations for the taxpayer.

Both changes together mean the integration surface v1 was built against no longer
exists. Not "needs updating" — the thing it connected to is gone. Any v2 is a
rebuild against a new target, not a port.

Two things are worth being clear about.

**First, the v1 implementation is not mine to carry forward.** Even if the
integration surface had not changed, the code belongs to UNA and the student
team. v2 does not extend v1, reuse it, or reimplement it.

**Second, and more interesting: the new regime created a problem that did not
previously have a tool.** TRIBU-CR enforces a rule with money attached —
electronic documents a business *receives* must be accepted within the first
eight business days of the following month, and if that window closes unanswered
the IVA credit is lost permanently. There is no retroactive fix.

Small and mid-size businesses lose money to this constantly. Documents arrive,
nobody accepts them, the window closes quietly, and the loss shows up later as a
tax credit that is simply not there. It is a deadline problem wearing a
compliance costume, and a deadline problem is a tractable thing to build for.

So v2 is not "Fractal Desk, rebuilt". It is one wedge of the problem, built
properly: **the deadline engine**. Not a CRM, not project management, not
invoicing. The narrowest thing that solves a problem people actually lose money
to.

That is [the build in this repository](./README.md) — my own independent work,
over synthetic data, with no keys and no live calls.

---

## Ownership, and what this document is not

**The Fractal Desk v1 implementation is the intellectual property of Universidad
Nacional de Costa Rica and the five students who built it.** It is not mine. I
supervised the project as client-side sponsor; I did not write the code, and I
have no claim on it.

Accordingly:

- No v1 source code appears in this repository, in any form.
- Nothing here reconstructs, reimplements or approximates v1.
- No v1 architecture, schema or design artefact is reproduced here.
- This document describes **how a delivery was run** — requirements, scope,
  acceptance, schedule, review, and what I would change. That work was mine, and
  it is the only part of v1 I am claiming.

**Part B of this repository — the deadline engine — is my own independent
build.** Different problem, different regulatory regime, different codebase,
written from scratch by me. It shares nothing with v1 but a domain.
