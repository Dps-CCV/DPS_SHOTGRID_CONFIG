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

HookBaseClass = sgtk.get_hook_baseclass()


class MayaObjectShaderPublishPlugin(HookBaseClass):
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
        <p>This plugin publishes shading networks for each object.</p>
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
        base_settings = super(MayaObjectShaderPublishPlugin, self).settings or {}

        # settings specific to this class
        maya_object_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published work files. Should"
                "correspond to a template defined in "
                "templates.yml.",
            }
        }

        # update the base settings
        base_settings.update(maya_object_publish_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """
        return ["maya.session.object_geo"]

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

        accepted = True
        publisher = self.parent
        template_name = settings["Publish Template"].value

        # ensure a work file template is available on the parent item
        work_template = item.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "A work template is required for the session item in order to "
                "publish session geometry. Not accepting session geom item."
            )
            accepted = False

        # ensure the publish template is defined and valid and that we also have
        publish_template = publisher.get_template_by_name(template_name)
        if not publish_template:
            self.logger.debug(
                "The valid publish template could not be determined for the "
                "session geometry item. Not accepting the item."
            )
            accepted = False

        # we've validated the publish template. add it to the item properties
        # for use in subsequent methods
        item.properties["publish_template"] = publish_template

        # because a publish template is configured, disable context change. This
        # is a temporary measure until the publisher handles context switching
        # natively.
        item.context_change_allowed = False

        obj = item.properties["object"]
        if len(_get_shading_groups_from_object(obj))==0:
            accepted = False

        if publisher.context.step['name'] in ['SHADING_A', 'TEXTURE_A']:
            return {"accepted": accepted, "checked": True}
        else:
            return {"accepted": False, "checked": False}

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
        return super(MayaObjectShaderPublishPlugin, self).validate(settings, item)

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

        item.properties["publish_type"] = "Maya Shading Network"
        obj = item.properties["object"]
        shading_groups = _get_shading_groups_from_object(obj)
        # Select them
        cmds.select(shading_groups, replace=True)

        try:
            self.parent.log_debug("Executing shaders export command:" )
            # Export to MB
            cmds.file(publish_path, force=True, type="mayaBinary", exportSelected=True)
        except Exception as e:
            self.logger.error("Failed to export Shaders: %s" % e)
            return

        # Now that the path has been generated, hand it off to the
        super(MayaObjectShaderPublishPlugin, self).publish(settings, item)


        # restore selection
        cmds.select(cur_selection)

        status = {"sg_status_list": "rev"}
        self.parent.sgtk.shotgun.update("Task", item.context.task['id'], status)
        # self.parent.sgtk.shotgun.update("Shot", item.context.entity['id'], status)

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


def _get_shading_groups_from_object(obj):
    """
    Gets all shading groups connected to an object and its children.

    :param obj: Object name
    :return: List of shading groups
    """

    if not cmds.objExists(obj):
        print("Object '%s' does not exist" % obj)
        return []

    shading_groups = set()

    # Get all shapes under this object (including children)
    shapes = cmds.listRelatives(obj, allDescendents=True, fullPath=True) or []

    # Also check if the object itself is a shape
    if cmds.nodeType(obj) in ['mesh', 'nurbsSurface', 'nurbsCurve']:
        shapes.append(obj)

    print("Found %d shapes under '%s'" % (len(shapes), obj))

    # For each shape, find connected shading groups
    for shape in shapes:
        # Get shading groups connected to this shape
        sgs = cmds.listConnections(shape, type='shadingEngine')

        if sgs:
            shading_groups.update(sgs)

    shading_groups = list(shading_groups)

    print("\nShading Groups connected to '%s':" % obj)
    for sg in shading_groups:
        print("  - %s" % sg)

    return shading_groups