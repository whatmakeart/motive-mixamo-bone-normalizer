# Motive / Mixamo Bone Normalizer 1.1.0

Install the ZIP without extracting it: Edit > Preferences > Add-ons > menu
at the upper right > Install from Disk. Choose the ZIP, then enable
**Motive / Mixamo Bone Normalizer**. 

Import the FBXs, select the armature objects in the viewport, press **N**, open
the **Retarget** tab, and click **Normalize Selected Armatures**. This works
with one or several rigs. In Rokoko, select Source and Target and rebuild the
bone list. 

Armature object names stay unchanged. Bone names become prefix-free Mixamo
names, such as Hips, LeftForeArm, RightToeBase, and LeftHandIndex1. Animation,
mesh vertex groups, constraints, drivers, and bone parenting are preserved.
Shared armature data and actions are isolated from unselected objects when
necessary. Bones are not added or removed.

**Preview Names** opens a wide, scrollable table showing the armature,
original bone name, and proposed name for every bone, including unchanged
names. The same list stays visible in the Retarget sidebar. The list's filter
can search for an armature, old name, or new name. Preview does not rename
bones or change Rokoko's matching integration.
The full report is also stored in the Blender Text Editor as **Bone
Normalization Report**. The original-to-new names are backed up in a JSON
Text datablock within the .blend file. Normalization supports Undo.

With the normalizer enabled, Rokoko's Build / Rebuild Bone List uses exact
counterpart names when both Source and Target have been normalized. LeftArm
matches LeftArm, and LeftShoulder matches LeftShoulder, even if saved Rokoko
aliases were incorrect. Numbered neck joints match their same-number joint
only; absent counterparts stay blank. This also applies to other unmatched
joints, including extra spines. 