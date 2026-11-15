"""Autodesk's public BuiltInCategory ids for documentation elements."""
OST = {
    -2003100: "OST_Sheets",
    -2000280: "OST_TitleBlocks",
    -2000510: "OST_Viewports",
    -2000279: "OST_Views",
    -2000300: "OST_TextNotes",
    -2000260: "OST_Dimensions",
    -2000150: "OST_GenericAnnotation",
    -2000051: "OST_Lines",
    -2002000: "OST_DetailComponents",
    -2000220: "OST_Grids",
    -2000240: "OST_Levels",
    -2000400: "OST_Matchline",
    -2006060: "OST_RevisionClouds",
    -2000530: "OST_ReferenceViewer",
    -2000535: "OST_Callouts",
    -2000200: "OST_Elev",
    -2000201: "OST_ElevationMarks",
    -2000173: "OST_ScheduleGraphics",
}

# model categories the plan linework is drawn for (Autodesk's public BuiltInCategory ids)
MODEL = {
    -2000011: "OST_Walls", -2000014: "OST_Windows", -2000023: "OST_Doors", -2000032: "OST_Floors",
    -2000035: "OST_Roofs", -2000038: "OST_Ceilings", -2000080: "OST_Furniture", -2000100: "OST_Columns",
    -2000120: "OST_Stairs", -2000151: "OST_GenericModel", -2001040: "OST_ElectricalEquipment",
    -2001120: "OST_LightingFixtures", -2001160: "OST_PlumbingFixtures", -2001320: "OST_StructuralFraming",
    -2001330: "OST_StructuralColumns", -2008000: "OST_DuctCurves", -2008010: "OST_DuctFitting",
    -2008013: "OST_DuctTerminal", -2008044: "OST_PipeCurves", -2008049: "OST_PipeFitting",
}


def name(category):
    """A layer name for a BuiltInCategory id: 'Doors' for OST_Doors, 'Category -2001350' when unnamed."""
    ost = MODEL.get(category) or OST.get(category)
    return ost[4:] if ost else f"Category {category}" if category else "Unassigned"
