# Motive / Mixamo Bone Normalizer 1.1.1

## Install

In Edit > Preferences > Get Extensions, open the menu at the upper right, choose Install from Disk, select the ZIP, and enable the extension. The manifest and both Python files are included at the ZIP's root.

## Use

1. Import the FBX files and select their armature objects in the viewport.
2. Press N, open Retarget, and click Preview Names to see every original and proposed name in a scrollable table. Preview does not rename bones.
3. Click Normalize Selected Armatures. Armature object names stay unchanged.
4. In Rokoko, select Source and Target and build or rebuild the bone list.

Keep this extension enabled for exact matching between normalized rigs. Missing counterparts stay blank, and bones are not added or removed. Neck1 and Neck2 retain their numbers; arms and shoulders remain separate. Finger ends use their own side and finger's fourth bone. A 3D suffix denotes an end only when a separate third finger joint exists above it.

Normalization preserves animation, mesh bindings, constraints, drivers, bone parents, transforms, and rest poses. Shared armatures and actions are isolated from unselected objects. Ambiguous duplicate names are reported and skipped. Reference poses and scale still need to suit retargeting. The operation supports Undo and stores a name backup and full report in the Blender Text Editor. The file permission is used to save Rokoko's custom bone naming schemes when that add-on is loaded.
