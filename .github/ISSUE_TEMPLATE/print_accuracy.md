---
name: Print differs from Revit's
about: Something is missing, extra, or drawn differently from Revit's own print
labels: accuracy
---

**What differs**

Which sheet and view type (plan, ceiling plan, section, elevation, schedule), and what is
missing, extra or different.

**Evidence**

A screenshot of Revit's print and of rvt-prt's print of the same area, side by side. Better
still, export the sheet from Revit as DXF or DWFx and paste the report of:

```
rvt-prt compare REVIT_EXPORT OUR_PRINT
```

**Is it a known limitation?**

Check `docs/limitations.md` first, and say if it is listed there.

**Versions**

- `rvt-prt --version`:
- Revit release that saved the file:
- Revit release that made the reference export:

**The model**

Do not attach a model unless you are sure you may share it. A small model you made yourself,
with one sheet that shows the difference and Revit's export of that sheet, is ideal.
