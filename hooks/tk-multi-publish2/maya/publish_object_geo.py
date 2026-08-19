# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import maya.cmds as cmds
import maya.mel as mel
import sgtk

from tank_vendor import six
from sgtk.platform.qt import QtCore, QtGui
import shutil

HookBaseClass = sgtk.get_hook_baseclass()


class MayaObjectGeometryPublishPlugin(HookBaseClass):
    """
    Plugin for publishing an open maya session.

    This hook relies on functionality found in the base file publisher hook in
    the publish2 app and should inherit from it in the configuration. The hook
    setting for this plugin should look something like this::

        hook: "{self}/publish_file.py:{engine}/tk-multi-publish2/basic/publish_session.py"

    """

    # NOTE: The plugin icon and name are defined by the base file plugin.

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        return """
        <p>This plugin publishes session geometry for the current session. Any
        session geometry will be exported to the path defined by this plugin's
        configured "Publish Template" setting. The plugin will fail to validate
        if the "AbcExport" plugin is not enabled or cannot be found.</p>
        """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """
        # inherit the settings from the base publish plugin
        base_settings = super(MayaObjectGeometryPublishPlugin, self).settings or {}

        # settings specific to this class
        maya_object_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published work files. Should"
                "correspond to a template defined in "
                "templates.yml.",
            },
            "Write Face Sets": {
                "type": "bool",
                "default": False,
                "description": "Writes face sets information to the resulting alembic file",
            },
            "Write Uvs": {
                "type": "bool",
                "default": False,
                "description": "Writes uvs information to the resulting alembic file",
            },
            "Write Uv Sets": {
                "type": "bool",
                "default": False,
                "description": "Writes uv sets information to the resulting alembic file",
            },
            "Write Color Sets": {
                "type": "bool",
                "default": False,
                "description": "Writes color sets information to the resulting alembic file",
            }

        }

        # update the base settings
        base_settings.update(maya_object_publish_settings)

        return base_settings

    def create_settings_widget(self, parent):
        """
        Creates a Qt widget for editing the plugin settings.

        :param parent: The parent QWidget
        :returns: A QWidget with the settings UI
        """
        # Create main widget
        widget = QtGui.QWidget(parent)
        layout = QtGui.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create checkboxes
        self.write_facesets_cb = QtGui.QCheckBox("Write Face Sets")
        self.write_facesets_cb.setToolTip("Writes face sets info to resulting alembic")
        layout.addWidget(self.write_facesets_cb)

        self.write_uvs_cb = QtGui.QCheckBox("Write Uvs")
        self.write_uvs_cb.setToolTip("Writes uvs info to resulting alembic")
        layout.addWidget(self.write_uvs_cb)

        self.write_uvSets_cb = QtGui.QCheckBox("Write Uv Sets")
        self.write_uvSets_cb.setToolTip("Writes uv sets info to resulting alembic")
        layout.addWidget(self.write_uvSets_cb)

        self.write_colorSets_cb = QtGui.QCheckBox("Write Color Sets")
        self.write_colorSets_cb.setToolTip("Writes color sets info to resulting alembic")
        layout.addWidget(self.write_colorSets_cb)

        # Add stretch to push checkboxes to the top
        layout.addStretch()

        return widget


    def get_ui_settings(self, widget):
        """
        Method called by the publisher to retrieve setting values from the UI.

        :param widget: The widget returned by create_settings_widget()
        :returns: Dictionary of setting names to values
        """
        ui_settings = {}

        ui_settings["Write Face Sets"] = self.write_facesets_cb.isChecked()
        ui_settings["Write Uvs"] = self.write_uvs_cb.isChecked()
        ui_settings["Write Uv Sets"] = self.write_uvSets_cb.isChecked()
        ui_settings["Write Color Sets"] = self.write_colorSets_cb.isChecked()

        return ui_settings

    def set_ui_settings(self, widget, settings):
        """
        Method called by the publisher to populate the UI with setting values.

        :param widget: The widget returned by create_settings_widget()
        :param settings: Dictionary of setting names to values
        """
        # Get the current context to modify checkbox states
        publisher = self.parent
        context = publisher.context

        # Helper function to get setting value
        def get_setting_value(settings, name, default):
            """Get setting value whether settings is a dict or list"""
            if isinstance(settings, dict):
                return settings.get(name, default)
            elif isinstance(settings, list):
                for setting in settings:
                    if hasattr(setting, 'name') and setting.name == name:
                        return setting.value
                return default
            else:
                return default

        # Set default values
        self.write_facesets_cb.setChecked(get_setting_value(settings, "Write Face Sets", False))
        self.write_uvs_cb.setChecked(get_setting_value(settings, "Write Uvs", False))
        self.write_uvSets_cb.setChecked(get_setting_value(settings, "Write Uv Sets", False))
        self.write_colorSets_cb.setChecked(get_setting_value(settings, "Write Color Sets", False))

        # Customize based on step
        if context.step:
            step_name = context.step.get("name", "").lower()

            if 'texture' in step_name or 'shading' in step_name or 'animation' in step_name:
                self.write_facesets_cb.setChecked(True)
                self.write_uvs_cb.setChecked(True)
                self.write_uvSets_cb.setChecked(True)
                self.write_colorSets_cb.setChecked(True)



    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """
        return ["maya.session.object_geo", "maya.session.object_geo_group", "maya.session.geometries"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A publish task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
                all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled
        """

        # Initialize return values
        accepted = True
        checked = False

        publisher = self.parent
        template_name = settings["Publish Template"].value

        # ============================================================================
        # VALIDATION CHECKS - Early returns for failed validations
        # ============================================================================

        # Check work template
        work_template = item.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "A work template is required for the session item in order to "
                "publish session geometry. Not accepting session geom item."
            )
            return {"accepted": False, "checked": False}

        # Check publish template
        publish_template = publisher.get_template_by_name(template_name)
        if not publish_template:
            self.logger.debug(
                "The valid publish template could not be determined for the "
                "session geometry item. Not accepting the item."
            )
            return {"accepted": False, "checked": False}

        # Store publish template for later use
        item.properties["publish_template"] = publish_template

        # Check Alembic export command availability
        if not mel.eval('exists "AbcExport"'):
            self.logger.debug(
                "Item not accepted because alembic export command 'AbcExport' "
                "is not available. Perhaps the plugin is not enabled?"
            )
            return {"accepted": False, "checked": False}

        # Disable context change (temporary measure)
        item.context_change_allowed = False

        # Special case: session geometries on Assets are not accepted
        if item.type == "maya.session.geometries" and publisher.context.entity['type'] == 'Asset':
            return {"accepted": False, "checked": False}

        # ============================================================================
        # GET PARENT NODE
        # ============================================================================

        if item.type != "maya.session.geometries":
            cur_selection = cmds.ls(selection=True)
            cmds.select(item.properties["object"])
            parentNode = cmds.listRelatives(cmds.ls(selection=True)[0], parent=True, fullPath=True)
            cmds.select(cur_selection)
        else:
            parentNode = _get_root_from_first_mesh()

        # ============================================================================
        # DETERMINE CHECKED STATE BASED ON STEP
        # ============================================================================

        step_name = publisher.context.step['name']

        # Define step categories
        MODELING_STEPS = ['MODEL', 'TEXTURE_A', 'CLAY_A', 'FOTOGRAMETRY_A', 'GROOM_A', 'MODEL_A', 'SCAN_A']
        ANIMATION_STEPS = ['TRACK_3D', 'LAYOUT', 'ANIMATION', 'CLOTH', 'CROWD', 'ANIMATION_A', 'CHARACTER_FX_A',
                           'CLOTH_A', 'LAYOUT_A', 'MODEL_A', 'SCAN_A']
        ANIMATION_SPECIFIC = ['ANIMATION', 'ANIMATION_A']

        if step_name in MODELING_STEPS:
            # Modeling steps: always checked
            checked = True

        elif step_name in ANIMATION_STEPS:
            # Animation-related steps: more complex logic

            # For animation-specific steps without animation, don't check
            if step_name in ANIMATION_SPECIFIC and not _geo_has_animation(parentNode):
                checked = False
            # For non-session geometries, check
            elif item.type != "maya.session.geometries":
                checked = True
            # Session geometries in animation steps: don't check
            else:
                checked = False

        else:
            # Unknown steps: don't check
            checked = False

        return {"accepted": accepted, "checked": checked}

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish. Returns a
        boolean to indicate validity.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :returns: True if item is valid, False otherwise.
        """

        path = _session_path()

        # ---- ensure the session has been saved

        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Maya session has not been saved."
            self.logger.error(error_msg, extra=_get_save_as_action())
            raise Exception(error_msg)

        # get the normalized path
        path = sgtk.util.ShotgunPath.normalize(path)

        # check that there is still geometry in the scene:
        if not cmds.ls(geometry=True, noIntermediate=True):
            error_msg = (
                "Validation failed because there is no geometry in the scene "
                "to be exported. You can uncheck this plugin or create "
                "geometry to export to avoid this error."
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # get the configured work file template

        work_template = item.properties.get("work_template")
        publish_template = item.properties.get("publish_template")

        # get the current scene path and extract fields from it using the work
        # template:
        work_fields = work_template.get_fields(path)

        # we want to override the {name} token of the publish path with the
        # name of the object being exported. get the name stored by the
        # collector and remove any non-alphanumeric characters

        work_fields["maya.object_name"] = item.properties.get("object_name")
        item.properties["publish_name"] = os.path.basename(str(item.properties.get("path")))[:-9]



        # ensure the fields work for the publish template
        missing_keys = publish_template.missing_keys(work_fields)
        if missing_keys:
            error_msg = (
                "Work file '%s' missing keys required for the "
                "publish template: %s" % (path, missing_keys)
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # create the publish path by applying the fields. store it in the item's
        # properties. This is the path we'll create and then publish in the base
        # publish plugin. Also set the publish_path to be explicit.
        work_fields["maya.object_name"] = item.properties["object_name"]
        item.properties["path"] = publish_template.apply_fields(work_fields)
        # item.properties["path"] = item.properties["path"][:-3]+".abc"
        item.properties["publish_path"] = item.properties["path"]

        # use the work file's version number when publishing
        if "version" in work_fields:
            item.properties["publish_version"] = work_fields["version"]


        # run the base class validation
        return super(MayaObjectGeometryPublishPlugin, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        publisher = self.parent


        # keep track of everything currently selected. we will restore at the
        # end of the publish method
        cur_selection = cmds.ls(selection=True)
        # get the path to create and publish
        publish_path = item.properties["path"]

        # ensure the publish folder exists:
        publish_folder = os.path.dirname(publish_path)
        self.parent.ensure_folder_exists(publish_folder)

        # set the alembic args that make the most sense when working with Mari.
        # These flags will ensure the export of an Alembic file that contains
        # all visible geometry from the current scene together with UV's and
        # face sets for use in Mari.
        alembic_args = [
            # # only renderable objects (visible and not templated)
            "-renderableOnly",
            "-worldSpace",
            "-dataformat",
            "ogawa",
        ]

        write_face_sets = settings.get("Write Face Sets").value
        write_uvs = settings.get("Write Uvs").value
        write_uv_sets = settings.get("Write Uv Sets").value
        write_color_sets = settings.get("Write Color Sets").value
        if write_face_sets:
            alembic_args.append("-writeFaceSets")
        if write_uvs:
            alembic_args.append("-uvWrite")
        if write_uv_sets:
            alembic_args.append("-writeUVSets")
        if write_color_sets:
            alembic_args.append("-writeColorSets")

        if item.type != "maya.session.geometries":
            item.properties["publish_type"] = "Alembic Cache"
            cmds.select(item.properties["object"])
            # if 'TEXTURE' or 'SHADING' in publisher.context.step['name']:
            #     bake_facesets_for_selection(remove_object_level_links=True, verbose=True)
            parentNode = cmds.listRelatives(cmds.ls(selection=True)[0], parent=True, fullPath = True )
            alembic_args.append("-root")
            alembic_args.append(cmds.ls(selection=True)[0])
        else:
            item.properties["publish_type"] = "Session Alembic Cache"
            parentNode = _get_root_from_first_mesh()

        if _geo_has_animation(parentNode) == True:
            start_frame, end_frame = _find_scene_animation_range()
            alembic_args.insert(0, "-frameRange %d %d" % (start_frame-50, end_frame))




        # Set the output path:
        # Note: The AbcExport command expects forward slashes!
        alembic_args.append("-file %s" % publish_path.replace("\\", "/"))

        # build the export command.  Note, use AbcExport -help in Maya for
        # more detailed Alembic export help
        abc_export_cmd = 'AbcExport -j "%s"' % " ".join(alembic_args)

        # ...and execute it:
        try:
            self.parent.log_debug("Executing command: %s" % abc_export_cmd)
            mel.eval(abc_export_cmd)
        except Exception as e:
            self.logger.error("Failed to export Geometry: %s" % e)
            return

        # Now that the path has been generated, hand it off to the
        super(MayaObjectGeometryPublishPlugin, self).publish(settings, item)


        # restore selection
        cmds.select(cur_selection)

        status = {"sg_status_list": "rev"}
        self.parent.sgtk.shotgun.update("Task", item.context.task['id'], status)
        # self.parent.sgtk.shotgun.update("Shot", item.context.entity['id'], status)

    def finalize(self, settings, item):

        ##EFECTOSCOPIO UNREGISTER AND DELETE ALL PUBLISHES
        self.logger.info(
            "Starting unregister and deletion of old publishes"
        )
        publisher = self.parent
        tk = publisher.sgtk
        engine = sgtk.platform.current_engine()
        order = [{'field_name': 'version_number', 'direction': 'asc'}]
        pubs = engine.shotgun.find("PublishedFile",[['task', 'is', engine.context.task], ['name', 'is', item.properties["publish_name"]]], ['path', 'version_number'], order)
        if len(pubs) < 5:
            return
        else:
            delete = pubs[5:]
            for d in delete:
                self.logger.info(
                    "Unregistering %s " % (d['path'])
                )
                # Grab the unregister command
                unreg_cmd = sgtk.get_command('unregister_folders', tk)
                parameters = {"entity": d}
                unreg_cmd.execute(parameters)
                shutil.rmtree(d['path'])
                self.logger.info(
                    " Folder %s was deleted" % (d['path'])
                )




def _find_scene_animation_range():

    """
    Find the animation range from the current scene.
    """
    # # look for any animation in the scene:
    # animation_curves = cmds.ls(typ="animCurve")
    #
    # # if there aren't any animation curves then just return
    # # a single frame:
    # if not animation_curves:
    #     return None, None

    # something in the scene is animated so return the
    # current timeline.  This could be extended if needed
    # to calculate the frame range of the animated curves.
    start = int(cmds.playbackOptions(q=True, min=True))
    end = int(cmds.playbackOptions(q=True, max=True))

    return start, end


def _geo_has_animation(node):
    nodos = cmds.listRelatives(node, ad=True, f=True)
    breakFlag = False
    if nodos != None:
        nodos.insert(0, node)

        for i in nodos:
            if cmds.nodeType(i) == "transform":
                animAttributes = cmds.listAnimatable(i)
                if animAttributes != None:
                    for attribute in animAttributes:
                        numKeyframes = cmds.keyframe(attribute, query=True, keyframeCount=True)
                        if numKeyframes > 0:
                            breakFlag = True
                            break
                else:
                    continue

            elif cmds.nodeType(i) == "mesh":
                attribute = i + ".inMesh"
                connections = cmds.listConnections(attribute, d=0)
                if connections != None:
                    breakFlag = True
                    break
            if breakFlag == True:
                break

    return breakFlag


def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = cmds.file(query=True, sn=True)

    if path is not None:
        path = six.ensure_str(path)

    return path


def _get_save_as_action():
    """
    Simple helper for returning a log action dict for saving the session
    """

    engine = sgtk.platform.current_engine()

    # default save callback
    callback = cmds.SaveScene

    # if workfiles2 is configured, use that for file save
    if "tk-multi-workfiles2" in engine.apps:
        app = engine.apps["tk-multi-workfiles2"]
        if hasattr(app, "show_file_save_dlg"):
            callback = app.show_file_save_dlg

    return {
        "action_button": {
            "label": "Save As...",
            "tooltip": "Save the current session",
            "callback": callback,
        }
    }


def _get_root_from_first_mesh():
    """
    Obtiene todas las mallas, selecciona la primera, y obtiene su nodo raíz.
    """
    # 1. Obtener todas las geometrías/meshes (shapes)
    all_meshes = cmds.ls(type='mesh', long=True)

    if not all_meshes:
        print("No meshes found in scene")
        return None

    # 2. Obtener el primer mesh
    first_mesh = all_meshes[0]
    print("First mesh shape: %s" % first_mesh)

    # 3. Obtener el transform del mesh (el padre del shape)
    transform = cmds.listRelatives(first_mesh, parent=True, fullPath=True)

    if not transform:
        print("No transform found for mesh")
        return None

    first_transform = transform[0]
    print("Transform node: %s" % first_transform)

    # 4. Obtener el nodo raíz
    root_node = _get_root_node(first_transform)
    print("Root node: %s" % root_node)

    return root_node


def _get_root_node(node):
    """
    Obtiene el nodo raíz de cualquier nodo dado.
    """
    current = node

    while True:
        parents = cmds.listRelatives(current, parent=True, fullPath=True)

        if not parents:
            # No hay más padres, este es el root
            break

        current = parents[0]

    # Devolver solo el nombre corto (sin path completo)
    return current.split('|')[-1]

import maya.cmds as cmds
import maya.mel as mel

# -----------------------------
# Helpers
# -----------------------------

def _get_selected_mesh_shapes():
    """
    From the current selection (transforms or shapes), return ALL descendant mesh shapes,
    at ANY depth, using long DAG paths.
    """
    sel = cmds.ls(sl=True, long=True) or []
    if not sel:
        cmds.warning("Nothing selected. Select one or more root transforms to process.")
        return []

    shapes = []

    # Expand selection to transforms (if shapes are selected, consider their parents as roots too)
    roots = set()
    for node in sel:
        nt = cmds.nodeType(node)
        if nt == "transform":
            roots.add(node)
        elif nt == "mesh":
            parent = cmds.listRelatives(node, parent=True, fullPath=True) or []
            if parent:
                roots.add(parent[0])

    # If user only selected meshes and not transforms, we still include those shapes explicitly
    explicit_meshes = [n for n in sel if cmds.nodeType(n) == "mesh"]
    shapes.extend(explicit_meshes)

    # For each root transform, get all descendant mesh shapes
    for root in roots:
        desc_meshes = cmds.listRelatives(root, allDescendents=True, noIntermediate=True, type="mesh", fullPath=True) or []
        shapes.extend(desc_meshes)

    # Deduplicate, preserve order
    seen = set()
    out = []
    for s in shapes:
        if s not in seen:
            seen.add(s)
            out.append(s)

    if not out:
        cmds.warning("No mesh shapes found under the selected nodes.")
    print(out)
    return out

def _get_shape_transform(shape_long):
    return (cmds.listRelatives(shape_long, parent=True, fullPath=True) or [None])[0]

def _expand_face_components(comps):
    """
    Expand component strings into explicit per-face strings using filterExpand.
    Returns a list like ["|pCube1|pCubeShape1.f[0]", ...].
    """
    if not comps:
        return []
    if isinstance(comps, (str,)):
        comps = [comps]
    expanded = cmds.filterExpand(comps, sm=34) or []  # sm=34 => polygon faces
    return expanded

def _parse_face_indices(face_components):
    """
    Given explicit face component strings (e.g., "|mesh|shape.f[12]"),
    return a set of face indices as integers.
    """
    indices = set()
    for comp in face_components or []:
        lb = comp.rfind("[")
        rb = comp.rfind("]")
        if lb != -1 and rb != -1:
            try:
                idx = int(comp[lb+1:rb])
                indices.add(idx)
            except ValueError:
                pass
    return indices

def _connected_shading_groups(shape_long):
    """
    Return shadingEngine nodes connected to the given mesh shape.
    """
    sgs = cmds.listConnections(shape_long, type="shadingEngine") or []
    # Deduplicate & keep order
    seen = set()
    out = []
    for sg in sgs:
        if sg not in seen:
            seen.add(sg)
            out.append(sg)
    return out

def _members_for_sg(sg):
    """
    Return members of shadingEngine set. Could include transforms, shapes, or components.
    """
    try:
        members = cmds.sets(sg, query=True) or []
    except Exception:
        members = []
    return members

def _is_member_object_level_for_shape(member, shape_long):
    """
    Determine if this member (string) represents object-level assignment for 'shape_long'.
    Accepts either the shape itself or its transform as an SG member.
    """
    member_long = (cmds.ls(member, long=True) or [member])[0]

    # Direct match to shape
    if member_long == shape_long or member == shape_long.split("|")[-1]:
        return True

    # Transform containing our shape?
    if cmds.nodeType(member_long) == "transform":
        child_shapes = cmds.listRelatives(member_long, shapes=True, ni=True, fullPath=True) or []
        return shape_long in child_shapes

    return False

def _collect_face_assignments_for_shape(shape_long, sgs):
    """
    Returns:
        assigned_faces_all: set of all face indices already assigned per-face across all SGs
        per_sg_faces: dict[sg] -> set(face indices)
        object_level_sgs: list of SGs that are assigned at object level for this shape
    """
    face_count = cmds.polyEvaluate(shape_long, face=True)
    per_sg_faces = {sg: set() for sg in sgs}
    assigned_faces_all = set()
    object_level_sgs = []

    for sg in sgs:
        members = _members_for_sg(sg)
        if not members:
            continue

        comp_members = []
        object_level_here = False

        for m in members:
            if m.startswith(shape_long + ".f[") or (m.endswith(".f]") and (shape_long.split("|")[-1] + ".f[") in m):
                comp_members.append(m)
            else:
                if _is_member_object_level_for_shape(m, shape_long):
                    object_level_here = True

        expanded = _expand_face_components(comp_members)
        indices = _parse_face_indices(expanded)
        per_sg_faces[sg] |= indices
        assigned_faces_all |= indices

        if object_level_here:
            object_level_sgs.append(sg)

    # Clamp indices just in case
    assigned_faces_all = {i for i in assigned_faces_all if 0 <= i < face_count}
    for sg in per_sg_faces:
        per_sg_faces[sg] = {i for i in per_sg_faces[sg] if 0 <= i < face_count}

    return assigned_faces_all, per_sg_faces, object_level_sgs, face_count

def _assign_faces_to_sg(shape_long, face_indices, sg):
    """
    Assign the given faces to the shadingEngine (per-face).
    """
    if not face_indices:
        return
    face_components = ["{}{}.f[{}]".format("", shape_long, idx) for idx in sorted(face_indices)]
    try:
        cmds.sets(face_components, edit=True, forceElement=sg)  # crucial call
    except Exception as ex:
        cmds.warning("Failed assigning faces to {}: {}".format(sg, ex))

def _remove_object_level_membership(shape_long, sg):
    """
    Remove object-level membership (shape or transform) from the SG for cleanliness.
    """
    xform = _get_shape_transform(shape_long)
    for target in [shape_long, xform]:
        if not target:
            continue
        try:
            cmds.sets(target, remove=sg)
        except Exception:
            pass

def _convert_object_level_materials_to_face_sets(shape_long, remove_object_level_links=True, verbose=True):
    """
    For a given mesh shape:
    - Detect object-level shading group assignments.
    - Compute unassigned faces (not already covered by per-face members of any SG).
    - For each object-level SG, assign the remaining unassigned faces to that SG.
    - Optionally remove object-level membership after conversion.

    This preserves any existing per-face overrides.
    """
    if cmds.nodeType(shape_long) != "mesh":
        return

    sgs = _connected_shading_groups(shape_long)
    if not sgs:
        return

    assigned_faces_all, per_sg_faces, object_level_sgs, face_count = _collect_face_assignments_for_shape(shape_long, sgs)

    if verbose:
        print("\n[FaceSets] Processing: {}".format(shape_long))
        print("  Connected SGs: {}".format(", ".join(sgs)))
        print("  Face count: {}".format(face_count))
        if object_level_sgs:
            print("  Object-level SGs detected: {}".format(", ".join(object_level_sgs)))
        else:
            print("  No object-level SGs on this shape.")

    if not object_level_sgs:
        return  # Nothing to convert

    all_faces = set(range(face_count))
    remaining = all_faces - assigned_faces_all

    for i, sg in enumerate(object_level_sgs):
        if not remaining:
            break
        to_assign = set(remaining)
        _assign_faces_to_sg(shape_long, to_assign, sg)
        remaining -= to_assign

        if remove_object_level_links:
            _remove_object_level_membership(shape_long, sg)

    if verbose:
        print("  Conversion done (remaining unassigned faces after pass: {}).".format(len(remaining)))

def bake_facesets_for_selection(remove_object_level_links=True, verbose=True):
    """
    Convert object-level material assignments to per-face for ALL descendant meshes
    under the currently selected root transform(s).
    """
    shapes = _get_selected_mesh_shapes()
    if not shapes:
        return []

    for s in shapes:
        convert_object_level_materials_to_face_sets(
            s,
            remove_object_level_links=remove_object_level_links,
            verbose=verbose
        )
    if verbose:
        print("\n[FaceSets] Finished. Processed {} mesh shape(s).".format(len(shapes)))
    return shapes

