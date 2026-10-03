"""Version 1.1.0: Normalize SELECTED Motive / OptiTrack / Mixamo armatures.

Import the FBXs, select their armature objects, open this file in Blender's
Text Editor, and click Run Script. No Rokoko Source / Target selection is
needed. Object names stay unchanged; corresponding bones get prefix-free
Mixamo names. Missing bones are not created, and extra bones are retained.

Blender's bone rename API updates animation, weights, constraints, drivers,
and bone parenting. Actions shared with other objects are copied first.
Renames use temporary names to prevent accidental .001 suffixes. Ambiguous
rigs are skipped and listed in "Bone Normalization Report". Original names
are also recorded in a JSON Text datablock in the .blend file.

Afterwards select any animated rig as Source and another rig as Target in
Rokoko, then Build / Rebuild Bone List. The script registers matching names
for extra joints if Rokoko is installed, without removing existing schemes.
Reference poses and scale still need to be suitable for retargeting.
Finger aliases include LThumb3End / RIndex3End and all corresponding fingers.
A 3D suffix denotes an endpoint only when a separate third finger segment
exists above it in the hierarchy; otherwise it denotes the third segment.
Numbered neck joints keep their numbers. For two normalized rigs, Rokoko's
bone list uses exact counterpart names; missing counterparts stay blank.
"""

import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime

DRY_RUN = False
REGISTER_ROKOKO_EXTRA_NAMES = True
SPINE = "__spine_chain__"
NORMALIZED_RIG_KEY = "_mocap_normalizer_names_version"
NORMALIZER_VERSION = 4


def compact(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def make_aliases():
    aliases = {}

    def add(canonical, *names):
        for name in (canonical,) + names:
            key = compact(name)
            existing = aliases.get(key)
            if existing is not None and existing != canonical:
                raise ValueError("Conflicting naming alias: " + name)
            aliases[key] = canonical

    add("Hips", "Hip", "Pelvis")
    add("Root", "Reference", "SceneRoot", "GlobalRoot")
    add("Neck", "Neck0")
    for i in range(1, 13):
        add("Neck" + str(i), "Neck_%02d" % i)
    add("Head")
    add("HeadTop_End", "HeadEnd", "HeadTopEnd", "HeadTip", "HeadVertex")
    add(SPINE, "Ab", "Abdomen", "Chest", "UpperChest", "LowerSpine",
        "MiddleSpine", "UpperSpine", "LowerBack", "UpperBack", "Torso", "Spine0")
    for i in range(12):
        add(SPINE, "Spine" + (str(i) if i else ""), "Spine%02d" % i)
    body = [
        ("Shoulder", ("Clavicle", "Collar", "CollarBone")),
        ("Arm", ("UpperArm", "UpArm", "UArm")),
        ("ForeArm", ("LowerArm", "FArm", "Elbow")),
        ("Hand", ("Wrist",)),
        ("UpLeg", ("UpperLeg", "Thigh",)),
        ("Leg", ("LowerLeg", "Shin", "Calf",)),
        ("Foot", ("Ankle",)),
        ("ToeBase", ("Toe", "Toes", "Ball",)),
        ("Toe_End", ("ToeEnd", "ToeTip", "ToeBaseEnd",)),
    ]
    fingers = (("Thumb", 1), ("Index", 2), ("Middle", 3), ("Ring", 4), ("Pinky", 5))
    for side, short in (("Left", "L"), ("Right", "R")):
        for segment, alternatives in body:
            names = [prefix + word for prefix in (side, short)
                     for word in (segment,) + alternatives]
            names += [word + "_" + short for word in (segment,) + alternatives]
            add(side + segment, *names)
        for finger, digit in fingers:
            terms = (finger, "Little") if finger == "Pinky" else (finger,)
            for number, anatomical in enumerate(("Proximal", "Medial", "Distal"), 1):
                names = []
                for prefix in (side, short):
                    for term in terms:
                        names += [prefix + "Hand" + term + str(number),
                                  prefix + term + str(number),
                                  prefix + term + anatomical,
                                  prefix + "Hand" + term + anatomical]
                        if number == 1:
                            names += [prefix + "Hand" + term, prefix + term]
                        if number == 3:
                            names += [prefix + "Hand" + term + "3D", prefix + term + "3D"]
                    names += [prefix + "Finger" + str(digit) + anatomical,
                              prefix + "Finger" + str(digit) + "_" + str(number)]
                names += [term + "_" + str(number) + "_" + short for term in terms]
                add(side + "Hand" + finger + str(number), *names)
            tip_names, meta_names = [], []
            for prefix in (side, short):
                for term in terms:
                    tip_names += [prefix + "Hand" + term + "4", prefix + term + "4",
                                  prefix + "Hand" + term + "End", prefix + term + "End",
                                  prefix + "Hand" + term + "Tip", prefix + term + "Tip",
                                  prefix + "Hand" + term + "3_End",
                                  prefix + term + "3_End"]
                    meta_names += [prefix + "Hand" + term + "0", prefix + term + "0",
                                   prefix + "Hand" + term + "Metacarpal",
                                   prefix + term + "Metacarpal"]
                tip_names += [prefix + "Finger" + str(digit) + "Tip",
                              prefix + "Finger" + str(digit) + "End"]
                meta_names += [prefix + "Finger" + str(digit) + "Metacarpal"]
            add(side + "Hand" + finger + "4", *tip_names)
            add(side + "Hand" + finger + "Metacarpal", *meta_names)
    return aliases


ALIASES = make_aliases()


def identify(name):
    """Match complete naming aliases, preserving side and segment numbers."""
    starts = [0] + [m.end() for m in re.finditer(r"[:|_.\s-]+", name)]
    for start in starts:
        suffix = name[start:]
        mixamo = re.match(r"mixamorig\d*[:|_.\s-]*", suffix, flags=re.I)
        if mixamo:
            start += mixamo.end()
            suffix = name[start:]
        canonical = ALIASES.get(compact(suffix))
        if canonical:
            return canonical, name[:start]
    return "", ""


def order_chain(bones):
    def depth(bone):
        result, parent = 0, bone.parent
        while parent:
            result += 1
            parent = parent.parent
        return result
    ordered = sorted(bones, key=lambda bone: (depth(bone), bone.name))
    for previous, current in zip(ordered, ordered[1:]):
        parent = current.parent
        while parent and parent != previous:
            parent = parent.parent
        if parent is None:
            raise ValueError("Spine candidates do not form a single chain; the rig may contain several actors.")
    return ordered


def build_plan(armature):
    bones = list(armature.data.bones)
    results = {bone.name: identify(bone.name) for bone in bones}
    notes = []
    for bone in bones:
        canonical, prefix = results[bone.name]
        if "Hand" not in canonical or not canonical.endswith("3"):
            continue
        if not compact(bone.name[len(prefix):]).endswith("3d"):
            continue
        parent = bone.parent
        while parent:
            parent_canonical, parent_prefix = results[parent.name]
            if parent_canonical == canonical and not compact(parent.name[len(parent_prefix):]).endswith("3d"):
                endpoint = canonical[:-1] + "4"
                results[bone.name] = (endpoint, prefix)
                notes.append("%s -> %s: follows third segment %s." % (bone.name, endpoint, parent.name))
                break
            parent = parent.parent
        else:
            notes.append("%s -> %s: no separate third segment above it; treated as distal joint." % (bone.name, canonical))
    prefixes = Counter(prefix for canonical, prefix in results.values() if canonical and prefix)
    # Apply observed actor prefixes to extra joints without guessing anatomy.
    observed = sorted(prefixes, key=lambda prefix: (-len(prefix), -prefixes[prefix], prefix))
    renames, unknown, spines = {}, [], []
    for bone in bones:
        canonical, prefix = results[bone.name]
        if canonical == SPINE:
            spines.append(bone)
            continue
        if canonical:
            renames[bone.name] = canonical
            continue
        clean = bone.name
        for prefix in observed:
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
                break
        clean = re.split(r"[:|]", clean)[-1]
        clean = re.sub(r"^mixamorig\d*[:|_.\s-]*", "", clean, flags=re.I)
        clean = clean.strip(" _.-") or bone.name
        renames[bone.name] = clean
        unknown.append(clean)
    for index, bone in enumerate(order_chain(spines)):
        renames[bone.name] = "Spine" + (str(index) if index else "")
    inverse = defaultdict(list)
    for old, new in renames.items():
        inverse[new.casefold()].append(old)
    collisions = [names for names in inverse.values() if len(names) > 1]
    if collisions:
        description = "; ".join(" / ".join(names) for names in collisions)
        raise ValueError("Different bones would get the same name: " + description)
    return {"objects": [armature], "data": armature.data, "names": renames,
            "unknown": unknown, "notes": notes,
            "changed": {a: b for a, b in renames.items() if a != b}}


def nla_strips(animation_data):
    def walk(strips):
        for strip in strips:
            yield strip
            nested = getattr(strip, "strips", None)
            if nested:
                yield from walk(nested)
    for track in getattr(animation_data, "nla_tracks", ()):
        yield from walk(track.strips)


def iter_fcurves(action, slot=None):
    seen = set()
    for curve in getattr(action, "fcurves", ()):
        seen.add(curve.as_pointer())
        yield curve
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for bag in getattr(strip, "channelbags", ()):
                if slot is not None and bag.slot_handle != slot.handle:
                    continue
                for curve in bag.fcurves:
                    if curve.as_pointer() not in seen:
                        seen.add(curve.as_pointer())
                        yield curve


def copy_action_if_shared(holder):
    action = getattr(holder, "action", None)
    if not action or action.users <= 1:
        return False
    slot = getattr(holder, "action_slot", None)
    identifier = getattr(slot, "identifier", None)
    replacement = action.copy()
    holder.action = replacement
    if identifier:
        for candidate in getattr(replacement, "slots", ()):
            if candidate.identifier == identifier:
                holder.action_slot = candidate
                break
    return True


def prepare_animation(plan):
    snapshots, seen, copies = [], set(), 0
    owners = list(plan["objects"]) + [plan["objects"][0].data]
    for owner in owners:
        data = owner.animation_data
        if not data:
            continue
        copies += int(copy_action_if_shared(data))
        holders = [data] + list(nla_strips(data))
        for holder in holders[1:]:
            copies += int(copy_action_if_shared(holder))
        for holder in holders:
            action = getattr(holder, "action", None)
            if not action or action.as_pointer() in seen:
                continue
            seen.add(action.as_pointer())
            for curve in iter_fcurves(action):
                snapshots.append((curve, curve.data_path))
            for group in getattr(action, "groups", ()):
                if group.name in plan["changed"]:
                    group.name = plan["changed"][group.name]
    return snapshots, copies


def remap_path(path, names):
    def replace(match):
        old = json.loads(match.group(2))
        new = names.get(old, old)
        return match.group(1) + "[" + json.dumps(new, ensure_ascii=False) + "]"
    return re.sub(r'((?:pose\.)?bones)\[("(?:[^"\\]|\\.)*")\]', replace, path)


def meshes_for(plan, bpy):
    objects = set(plan["objects"])
    for obj in bpy.data.objects:
        if hasattr(obj, "vertex_groups") and any(
                mod.type == "ARMATURE" and mod.object in objects for mod in obj.modifiers):
            yield obj


def validate_weights(plan, bpy):
    changed = plan["changed"]
    for mesh in meshes_for(plan, bpy):
        for old, new in changed.items():
            if mesh.vertex_groups.get(old) and mesh.vertex_groups.get(new) and new not in changed:
                raise ValueError("Mesh %s already has an unrelated vertex group named %s." % (mesh.name, new))


def apply_plan(plan, bpy):
    selected = set(plan["objects"])
    outside_users = [obj for obj in bpy.data.objects
                     if obj.type == "ARMATURE" and obj.data == plan["data"] and obj not in selected]
    if outside_users:
        isolated = plan["data"].copy()
        for obj in plan["objects"]:
            obj.data = isolated
        plan["data"] = isolated
    snapshots, copies = prepare_animation(plan)
    temporary = []
    token = uuid.uuid4().hex[:12]
    # Two passes also move bound vertex groups out of destination names.
    for index, (old, new) in enumerate(plan["changed"].items()):
        bone = plan["data"].bones.get(old)
        temp = "__mocap_%s_%d" % (token, index)
        bone.name = temp
        temporary.append((bone, new))
    for bone, new in temporary:
        bone.name = new
        if bone.name != new:
            raise RuntimeError("Blender could not assign the requested bone name: " + new)
    for curve, original_path in snapshots:
        curve.data_path = remap_path(original_path, plan["changed"])
    for obj in plan["objects"]:
        for prop in obj.bl_rna.properties:
            if prop.identifier.startswith("rsl_actor_") and prop.type == "STRING":
                value = getattr(obj, prop.identifier, "")
                if value in plan["changed"]:
                    setattr(obj, prop.identifier, plan["changed"][value])
        obj.update_tag()
    return copies


def rokoko_role(name):
    """Semantic labels for exact pairs, keeping arms separate from clavicles."""
    if re.fullmatch(r"Spine\d*", name):
        return "spine"
    common = {"Hips": "hip", "Neck": "neck", "Head": "head"}
    if name in common:
        return common[name]
    parts = {"Shoulder": "Shoulder", "Arm": "UpperArm", "ForeArm": "LowerArm",
             "Hand": "Hand", "UpLeg": "UpLeg", "Leg": "Leg", "Foot": "Foot",
             "ToeBase": "Toe"}
    for side in ("Left", "Right"):
        if not name.startswith(side):
            continue
        segment = name[len(side):]
        if segment in parts:
            return side.lower() + parts[segment]
        match = re.fullmatch(r"Hand(Thumb|Index|Middle|Ring|Pinky)([123])", segment)
        if match:
            finger, number = match.groups()
            finger = "Little" if finger == "Pinky" else finger
            return side.lower() + finger + ("Proximal", "Medial", "Distal")[int(number) - 1]
    return "custom_bone_" + name.lower()


def exact_retarget_matches(source, target):
    """Match animated source bones to existing same-name target bones only."""
    data = source.animation_data
    action = getattr(data, "action", None)
    if action is None:
        return {}
    slot = getattr(data, "action_slot", None)
    animated = {}
    for curve in iter_fcurves(action, slot=slot):
        match = re.match(r'pose\.bones\[("(?:[^"\\]|\\.)*")\]', curve.data_path)
        if match:
            name = json.loads(match.group(1))
            if source.pose.bones.get(name) is not None:
                animated[name] = None
    pairs = {}
    for name in animated:
        counterpart = target.pose.bones.get(name)
        pairs[name] = (counterpart.name if counterpart is not None else "", rokoko_role(name))
    return pairs


def rokoko_detection_modules():
    for module_name, module in list(sys.modules.items()):
        if module_name.endswith(".core.detection_manager") and hasattr(module, "bone_detection_list"):
            yield module


def install_rokoko_exact_matching():
    """Scope the integration to pairs processed by this normalizer."""
    hooked = 0
    for detection in rokoko_detection_modules():
        original = getattr(detection, "detect_retarget_bones", None)
        if original is None or getattr(original, "_mocap_exact_matching", False):
            continue

        def exact_detector(*args, _module=detection, _original=original, **kwargs):
            retargeting = getattr(_module, "retargeting", None)
            source = retargeting.get_source_armature() if retargeting is not None else None
            target = retargeting.get_target_armature() if retargeting is not None else None
            if (source is not None and target is not None
                    and source.get(NORMALIZED_RIG_KEY, 0)
                    and target.get(NORMALIZED_RIG_KEY, 0)):
                return exact_retarget_matches(source, target)
            return _original(*args, **kwargs)

        exact_detector._mocap_exact_matching = True
        exact_detector._mocap_original_detector = original
        detection.detect_retarget_bones = exact_detector
        hooked += 1
    return hooked


def uninstall_rokoko_exact_matching():
    for detection in rokoko_detection_modules():
        wrapper = getattr(detection, "detect_retarget_bones", None)
        if getattr(wrapper, "_mocap_exact_matching", False):
            detection.detect_retarget_bones = wrapper._mocap_original_detector


def register_rokoko_names(names):
    """Generic same-name pairs let Rokoko detect extras in either direction."""
    detection = None
    detection = next(rokoko_detection_modules(), None)
    if detection is None:
        return "Rokoko is not loaded; normalization still works without it."
    scheme_name = detection.__package__ + ".custom_schemes_manager"
    schemes = sys.modules.get(scheme_name)
    added = 0
    for name in sorted(names):
        lower = name.lower()
        standard = detection.standardize_bone_name(name)
        recognized = any(lower in values or standard in values
                         for key, values in detection.bone_detection_list.items()
                         if key != "chest")
        if recognized:
            continue
        key = "custom_bone_" + lower
        detection.bone_detection_list_custom[key] = [lower, lower]
        added += 1
    if added:
        if schemes and hasattr(schemes, "save_to_file_and_update"):
            schemes.save_to_file_and_update()
        else:
            detection.bone_detection_list = detection.combine_lists(
                detection.bone_detection_list_unmodified, detection.bone_detection_list_custom)
    return "Rokoko: registered %d additional prefix-free names. Normalized rig pairs use exact names." % added


def clear_stale_rokoko_list(context, selected, bpy):
    scene = context.scene
    if not hasattr(scene, "rsl_retargeting_bone_list"):
        return
    for key in ("rsl_retargeting_armature_source", "rsl_retargeting_armature_target"):
        value = getattr(scene, key, None)
        # Add-on versions use either strings or object pointers. Avoid get(None).
        obj = bpy.data.objects.get(value) if isinstance(value, str) and value else value
        if obj in selected:
            scene.rsl_retargeting_bone_list.clear()
            return


def normalize_selected(context, dry_run=DRY_RUN, register_names=REGISTER_ROKOKO_EXTRA_NAMES):
    import bpy
    selected = [obj for obj in context.selected_objects if obj.type == "ARMATURE"]
    if not selected:
        raise ValueError("Select one or more armature objects in the viewport first.")
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    plans, skipped, data_plans = [], [], {}
    for obj in sorted(selected, key=lambda item: item.name):
        try:
            if not obj.is_editable or not obj.data.is_editable:
                raise ValueError("Linked armature is not editable; make it local first.")
            pointer = obj.data.as_pointer()
            if pointer in data_plans:
                data_plans[pointer]["objects"].append(obj)
                continue
            plan = build_plan(obj)
            data_plans[pointer] = plan
            plans.append(plan)
        except ValueError as exc:
            skipped.append((obj.name, str(exc)))
    safe_plans = []
    for plan in plans:
        try:
            validate_weights(plan, bpy)
            safe_plans.append(plan)
        except ValueError as exc:
            skipped.extend((obj.name, str(exc)) for obj in plan["objects"])
    plans = safe_plans
    if not plans:
        raise ValueError("No armatures could be normalized. " + "; ".join(a + ": " + b for a, b in skipped))
    backup = {"version": NORMALIZER_VERSION, "created": datetime.now().isoformat(), "armatures": [
        {"objects": [obj.name for obj in plan["objects"]], "bone_names": plan["names"]}
        for plan in plans]}
    changes = sum(len(plan["changed"]) for plan in plans)
    if not dry_run and changes:
        text = bpy.data.texts.new("Bone Names Before Normalization.json")
        text.write(json.dumps(backup, indent=2))
    copies = 0
    if not dry_run:
        for plan in plans:
            if plan["changed"]:
                copies += apply_plan(plan, bpy)
            for obj in plan["objects"]:
                obj[NORMALIZED_RIG_KEY] = NORMALIZER_VERSION
        install_rokoko_exact_matching()
        clear_stale_rokoko_list(context, set(selected), bpy)
    all_names = {name for plan in plans for name in plan["names"].values()}
    plugin_status = ""
    if register_names and not dry_run:
        try:
            plugin_status = register_rokoko_names(all_names)
        except Exception as exc:
            plugin_status = "Bones normalized; Rokoko extra-name registration failed: " + str(exc)
    rig_count = sum(len(plan["objects"]) for plan in plans)
    summary = "%d armatures; %d bone names %s; %d skipped." % (
        rig_count, changes, "planned" if dry_run else "changed", len(skipped))
    lines = ["MOTIVE / MIXAMO BONE NORMALIZATION v4", summary,
             "Armature object names, rest poses, bone counts and transforms are preserved.",
             "Shared actions copied: %d" % copies, plugin_status, ""]
    for plan in plans:
        lines.append("ARMATURE: " + ", ".join(obj.name for obj in plan["objects"]))
        lines.extend("  %s -> %s" % (old, new) for old, new in plan["names"].items())
        lines.extend("  NOTE: " + note for note in plan["notes"])
        if plan["unknown"]:
            lines.append("  Extra names cleaned only (no anatomical guess): " + ", ".join(plan["unknown"]))
        lines.append("")
    for name, reason in skipped:
        lines.append("SKIPPED %s: %s" % (name, reason))
    lines.extend(["", "Next: choose Source and Target in Rokoko; Build / Rebuild Bone List.",
                  "Missing joints are not created. Review the mapping and both reference poses.",
                  "Optional: change DRY_RUN at the top to preview names."])
    report = "\n".join(lines) + "\n"
    text = bpy.data.texts.get("Bone Normalization Report") or bpy.data.texts.new("Bone Normalization Report")
    text.clear()
    text.write(report)
    context.view_layer.update()
    print(report)
    return {"summary": summary, "plans": plans, "skipped": skipped, "changes": changes,
            "plugin_status": plugin_status, "report": report}


def main():
    import bpy

    class OBJECT_OT_normalize_mocap_bone_names(bpy.types.Operator):
        bl_idname = "object.normalize_mocap_bone_names"
        bl_label = "Normalize Motive / Mixamo Bone Names"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context):
            try:
                result = normalize_selected(context)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            self.report({"WARNING"} if result["skipped"] else {"INFO"}, result["summary"])
            return {"FINISHED"}

    existing = getattr(bpy.types, "OBJECT_OT_normalize_mocap_bone_names", None)
    if existing:
        bpy.utils.unregister_class(existing)
    bpy.utils.register_class(OBJECT_OT_normalize_mocap_bone_names)
    bpy.ops.object.normalize_mocap_bone_names()


if __name__ == "__main__":
    main()
