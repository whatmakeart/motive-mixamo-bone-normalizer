# SPDX-License-Identifier: GPL-3.0-or-later
"""Installable interface for selected-armature Motive / Mixamo normalization."""

bl_info = {
    "name": "Motive / Mixamo Bone Normalizer",
    "author": "Blender Vibes",
    "version": (1, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D Viewport > Sidebar > Retarget",
    "description": "Normalize selected OptiTrack/Motive and Mixamo bone names for retargeting",
    "category": "Rigging",
}

import textwrap
import bpy
from bpy.app.handlers import persistent
from . import core


def armatures(context):
    return [obj for obj in context.selected_objects if obj.type == "ARMATURE"]


class MOCAP_PG_name_preview(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(default="")
    armature_name: bpy.props.StringProperty(default="")
    original_name: bpy.props.StringProperty(default="")
    proposed_name: bpy.props.StringProperty(default="")
    changed: bpy.props.BoolProperty(default=False)


def name_columns(layout, armature_name, original, proposed, icon="NONE"):
    columns = layout.split(factor=0.24, align=True)
    columns.label(text=armature_name, icon=icon)
    names = columns.split(factor=0.5, align=True)
    names.label(text=original)
    names.label(text=proposed)


class MOCAP_UL_name_preview(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # Using CHECKMARK or CHECKBOX_HL for visual confirmation
        status_icon = "FILE_REFRESH" if item.changed else "CHECKMARK"
        name_columns(
            layout,
            item.armature_name,
            item.original_name,
            item.proposed_name,
            icon=status_icon,
        )


def store_preview(scene, result, preview_only):
    scene.mocap_normalizer_preview_names.clear()
    for plan in result.get("plans", []):
        for obj in plan.get("objects", []):
            for original, proposed in plan.get("names", {}).items():
                item = scene.mocap_normalizer_preview_names.add()
                item.armature_name = obj.name
                item.original_name = original
                item.proposed_name = proposed
                item.changed = original != proposed
                item.name = f"{obj.name} {original} {proposed}"

    scene.mocap_normalizer_preview_index = 0
    scene.mocap_normalizer_preview_title = (
        "Preview Names" if preview_only else "Last Applied Names"
    )
    scene.mocap_normalizer_preview_errors = "\n".join(
        f"Skipped {name}: {reason}" for name, reason in result.get("skipped", [])
    )


def draw_preview(layout, scene, list_id, rows):
    layout.label(text=scene.mocap_normalizer_preview_title, icon="BONE_DATA")
    name_columns(layout.row(align=True), "Armature", "Current Name", "Proposed Name")
    layout.template_list(
        "MOCAP_UL_name_preview",
        list_id,
        scene,
        "mocap_normalizer_preview_names",
        scene,
        "mocap_normalizer_preview_index",
        rows=rows,
        maxrows=rows,
    )
    if scene.mocap_normalizer_preview_errors:
        box = layout.box()
        wrap_width = 80 if rows > 8 else 38
        for line in scene.mocap_normalizer_preview_errors.splitlines():
            for wrapped in textwrap.wrap(line, width=wrap_width):
                box.label(text=wrapped)


class MOCAP_OT_normalize_selected_bones(bpy.types.Operator):
    bl_idname = "object.mocap_normalize_selected_bones"
    bl_label = "Normalize Selected Armatures"
    bl_description = "Remove actor prefixes and standardize bones while preserving animation and mesh bindings"
    bl_options = {"REGISTER", "UNDO"}

    preview_only: bpy.props.BoolProperty(
        name="Preview only",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(armatures(context))

    def invoke(self, context, event):
        result = self.execute(context)
        if self.preview_only and result == {"FINISHED"}:
            return context.window_manager.invoke_popup(self, width=960)
        return result

    def draw(self, context):
        draw_preview(self.layout, context.scene, "popup", rows=16)
        self.layout.label(text=context.scene.mocap_normalizer_status)
        self.layout.label(
            text="Preview only. Scroll to review all bones; names have not been changed."
        )

    def execute(self, context):
        try:
            result = core.normalize_selected(context, dry_run=self.preview_only)
        except Exception as exc:
            message = str(exc)
            context.scene.mocap_normalizer_status = message
            context.scene.mocap_normalizer_preview_names.clear()
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        context.scene.mocap_normalizer_status = result.get("summary", "")
        store_preview(context.scene, result, self.preview_only)
        self.report(
            {"WARNING"} if result.get("skipped") else {"INFO"},
            result.get("summary", "Complete"),
        )
        return {"FINISHED"}


class MOCAP_PT_bone_normalizer(bpy.types.Panel):
    bl_idname = "MOCAP_PT_bone_normalizer"
    bl_label = "Motive / Mixamo Bones"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Retarget"

    def draw(self, context):
        layout = self.layout
        count = len(armatures(context))
        plural = "" if count == 1 else "s"
        layout.label(text=f"{count} armature{plural} selected", icon="ARMATURE_DATA")

        row = layout.row()
        row.scale_y = 1.5
        row.enabled = count > 0
        op = row.operator(MOCAP_OT_normalize_selected_bones.bl_idname, icon="FILE_REFRESH")
        op.preview_only = False

        row = layout.row()
        row.enabled = count > 0
        row.operator_context = "INVOKE_DEFAULT"
        op = row.operator(
            MOCAP_OT_normalize_selected_bones.bl_idname,
            text="Preview Names",
            icon="VIEWZOOM",
        )
        op.preview_only = True

        layout.separator()
        layout.label(text="Then rebuild Rokoko's bone list.")
        layout.label(text="Normalized rigs match by exact names.")
        layout.label(text="Object names and bone counts are kept.")

        status = context.scene.mocap_normalizer_status
        if status:
            box = layout.box()
            for line in textwrap.wrap(status, width=38):
                box.label(text=line)

        if len(context.scene.mocap_normalizer_preview_names) > 0:
            draw_preview(layout, context.scene, "sidebar", rows=8)

        layout.label(text="Detailed report: Blender Text Editor", icon="TEXT")
        layout.label(text="Bone Normalization Report")


CLASSES = (
    MOCAP_PG_name_preview,
    MOCAP_UL_name_preview,
    MOCAP_OT_normalize_selected_bones,
    MOCAP_PT_bone_normalizer,
)

SCENE_PROPERTIES = (
    "mocap_normalizer_status",
    "mocap_normalizer_preview_names",
    "mocap_normalizer_preview_index",
    "mocap_normalizer_preview_title",
    "mocap_normalizer_preview_errors",
)


@persistent
def install_exact_matching_after_load(_dummy):
    core.install_rokoko_exact_matching()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.mocap_normalizer_status = bpy.props.StringProperty(
        name="Last normalization result", default=""
    )
    bpy.types.Scene.mocap_normalizer_preview_names = bpy.props.CollectionProperty(
        type=MOCAP_PG_name_preview, options={"SKIP_SAVE"}
    )
    bpy.types.Scene.mocap_normalizer_preview_index = bpy.props.IntProperty(
        default=0, options={"SKIP_SAVE"}
    )
    bpy.types.Scene.mocap_normalizer_preview_title = bpy.props.StringProperty(
        default="", options={"SKIP_SAVE"}
    )
    bpy.types.Scene.mocap_normalizer_preview_errors = bpy.props.StringProperty(
        default="", options={"SKIP_SAVE"}
    )

    if install_exact_matching_after_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(install_exact_matching_after_load)

    core.install_rokoko_exact_matching()


def unregister():
    if install_exact_matching_after_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(install_exact_matching_after_load)

    core.uninstall_rokoko_exact_matching()

    for prop in reversed(SCENE_PROPERTIES):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()