# Clean-room policy

rvt-prt is a clean-room implementation of a reader and printer for the Autodesk Revit on-disk
format. Every format-level finding in the repository is derived from **public** sources. This
document states the policy in enforceable terms so contributors and auditors can verify.

## Accepted sources

Any of these are fine for contributors to use when adding new findings or decoders:

1. **Public byte observations.** Opening a Revit file and documenting what its bytes contain.
   The file can come from anywhere: Autodesk's publicly distributed sample projects, openly
   licensed test models, files the contributor created themselves, or files a user has
   explicitly authorized sharing. A Revit file carries its own class and field catalog
   (`Formats/Latest`), and records are decoded from that catalog. The observations are
   independent of any Autodesk source code.
2. **Revit's own output for a file.** What Revit prints and exports for a model (PDF, DXF,
   DWFx, IFC), and the values its user interface and public API report for an element. These
   show **what Revit draws or reports**, which is how a field observed in the bytes is tied to
   its meaning. They document Revit's output, not its implementation.
3. **Previously-published reverse-engineering work.**
   [rvt-rs](https://github.com/DrunkOnJava/rvt-rs) (Apache-2.0, with its own
   [clean-room policy](https://github.com/DrunkOnJava/rvt-rs/blob/main/CLEANROOM.md)), and other
   public projects and papers on the Revit format. Parts of rvt-rs's reader are ported here and
   credited in `NOTICE`. Contributors should cite the source in the PR description.
4. **Public specifications.** Microsoft Compound File Binary ([MS-CFB]), RFC 1950 to 1952
   (zlib, DEFLATE, gzip), buildingSMART IFC, and the PDF, DXF and DWFx (XPS) specifications.
5. **Autodesk's public documentation** of what Revit's features do: the user manual, and the
   public API documentation for what a parameter or setting means to a user. It is a reference
   for behaviour, not for how anything is stored.

## Forbidden sources

Do not use these. Findings derived from them will be rejected at PR review and, if merged
accidentally, removed in a subsequent commit.

1. **Autodesk SDK source code.** Revit SDK headers and samples beyond the publicly documented
   API surface are off limits.
2. **Open Design Alliance (ODA) SDK source.** The ODA's Revit and BIM reader internals are
   commercially licensed. Do not copy, paraphrase, or translate them.
3. **Leaked internal documentation.** Format specifications obtained through unauthorized means
   (breaches, disclosures, internal Autodesk documents not published on public channels) must
   not be used.
4. **NDA material.** If a contributor has signed an NDA with Autodesk, the ODA, or a related
   party that covers Revit internals, they cannot contribute findings that their NDA covers.
   They remain welcome to contribute to areas it does not cover (rendering, tests, CI, docs,
   tooling).
5. **Revit's implementation.** Disassembled or decompiled Revit code, reconstructed pseudocode
   of its internal functions, and anything read out of a running Revit (a debugger, memory
   reads, hooks or traces of its internal functions). The format is learned from the files and
   from what Revit outputs, not from inside the program.
6. **Copied code under an incompatible licence.** Code from GPL, LGPL or AGPL projects is not
   copied or translated into this Apache-2.0 tree. Reading such a project to learn what an
   export contains is fine: describe the behaviour in your own words and write the code from
   that description.

## Contributor declaration

When opening a non-trivial PR that adds format-level findings, the contributor confirms the
following in the PR description:

> "The changes in this PR are based on [list of sources from §Accepted sources]. I have not used
> Autodesk SDK source, ODA SDK source, leaked internal documentation, NDA material, or Revit's
> implementation (decompiled code, or a debugger on a running Revit), and I have not copied or
> translated code under an incompatible licence."

A one-sentence equivalent is fine. The point is that the finding's provenance is on record.

For routine PRs (docs, tests, refactors, rendering, tooling), this declaration isn't required.
It applies specifically to format findings: a newly decoded field, record or class, or its
meaning.

## Handling suspicious contributions

If a reviewer has reason to believe a PR's findings come from a forbidden source, the reviewer:

1. Asks the contributor privately (not in the public PR) to confirm the source. Respects that
   contributors may have legitimate NDA constraints preventing disclosure of specific details.
2. If the source cannot be confirmed as an accepted one, the PR is declined and the finding
   does not land. The contributor is not blocked from future work on other parts of the project.
3. If a finding later turns out to have come from a forbidden source after merging, the commit
   is reverted, the affected code paths are re-derived clean-room by a different contributor,
   and the project posts a correction note.

## Why this matters

- Trust with the Autodesk, ODA and buildingSMART ecosystem. A project that scrupulously
  respects IP boundaries is more credible and less likely to invite litigation threats.
- Downstream users can rely on rvt-prt's own code being Apache-2.0 with clean-room provenance:
  no IP-contamination risk from the code itself. (One dependency, PyMuPDF, has its own licence
  terms. See the README.)
- Contributors who want to work on the project without signing an NDA get a clear path.

## Legal posture

rvt-prt is intended as a clean-room interoperability implementation. It does not use Autodesk or
ODA SDK sources, leaked documentation, or decompiled proprietary implementation code. **Users
with specific legal constraints should evaluate the project with their own counsel.** This
document describes process and discipline; it is not legal advice.
