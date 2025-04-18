﻿# Copyright (c) 2017 Shotgun Software Inc.
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

import sys
sys.path.append("L:\\MAYA_SCRIPTS\\PYTHON\\DF")
sys.path.append("L:\\MAYA_SCRIPTS\\MEL\\DF")
import df_USD_geoExport_DPS


class MayaObjectGeometryUSDPublishPlugin(HookBaseClass):
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
        base_settings = super(MayaObjectGeometryUSDPublishPlugin, self).settings or {}

        # settings specific to this class
        maya_object_usd_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published work files. Should"
                "correspond to a template defined in "
                "templates.yml.",
            }
        }

        # update the base settings
        base_settings.update(maya_object_usd_publish_settings)

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
        self.logger.info(template_name)

        # ensure a work file template is available on the parent item
        work_template = item.parent.properties.get("work_template")
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
        item.properties["publish_type"] = "USD"

        # check that the AbcExport command is available!
        if not mel.eval('exists "AbcExport"'):
            self.logger.debug(
                "Item not accepted because alembic export command 'AbcExport' "
                "is not available. Perhaps the plugin is not enabled?"
            )
            accepted = False

        # because a publish template is configured, disable context change. This
        # is a temporary measure until the publisher handles context switching
        # natively.
        item.context_change_allowed = False

        if publisher.context.step['name'] in ['TRACK_3D', 'LAYOUT', 'ANIMATION', 'CLOTH', 'CROWD', 'MODEL', 'TEXTURE_A', 'ANIMATION_A', 'CHARACTER_FX_A', 'CLOTH_A', 'CLAY_A', 'FOTOGRAMETRY_A', 'GROOM_A', 'LAYOUT_A', 'MODEL_A', 'SCAN_A']:
            return {"accepted": accepted, "checked": False}
        else:
            return {"accepted": accepted, "checked": False}
            
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
        publisher = self.parent

        # ---- ensure the session has been saved
        publish_template = publisher.get_template_by_name(settings['Publish Template'].value)

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
        work_template = item.parent.properties.get("work_template")

        #publish_template = item.properties.get("publish_template")
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
        return super(MayaObjectGeometryUSDPublishPlugin, self).validate(settings, item)    
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

        cmds.select(item.properties["object"])
        self.logger.info(item.properties["object"])

        # get the path to create and publish
        publish_path = item.properties["path"]

        # ensure the publish folder exists:
        publish_folder = os.path.dirname(publish_path)
        self.parent.ensure_folder_exists(publish_folder)

        publish_path.replace("\\", "/")
        item.properties["path"] = item.properties["path"].replace(".usd", "_geo.usd")
        item.properties["publish_path"] = item.properties["path"]
        item.properties["publish_name"] = os.path.basename(item.properties["path"])[:-4]

        try:
            self.parent.log_debug("Executing usd")
            if publisher.context.step['name'] not in  ["MODEL", "MODEL_A", "TEXTURE", "TEXTURE_A", "SHADING", "SHADING_A", "FOTOGRAMETRY_A", "CLAY_A", "SCAN_A"]:
                options = ";exportDisplayColor=1;exportColorSets=0;mergeTransformAndShape=1;exportComponentTags=0;defaultUSDFormat=usdc;jobContext=[Arnold];materialsScopeName=mtl"
            else:
                options = ";readAnimData=1;exportDisplayColor=1;exportColorSets=0;mergeTransformAndShape=1;exportComponentTags=0;defaultUSDFormat=usdc;jobContext=[Arnold];materialsScopeName=mtl"
            df_USD_geoExport_DPS.main(publish_path.replace("\\", "/"), 'basemesh', 'proxy', options)

        except Exception as e:
            self.logger.error("Failed to export USD: %s" % e)
            return

        # Now that the path has been generated, hand it off to the
        super(MayaObjectGeometryUSDPublishPlugin, self).publish(settings, item)

        # get the path to create and publish
        item.properties["path"] = item.properties["path"].replace("_geo.usd", ".usda")
        item.properties["publish_path"] = item.properties["path"]
        item.properties["publish_name"] = os.path.basename(item.properties["path"])[:-4]


        # Now that the path has been generated, hand it off to the
        super(MayaObjectGeometryUSDPublishPlugin, self).publish(settings, item)

        # get the path to create and publish
        item.properties["path"] = item.properties["path"].replace(".usda", "_payload.usda")
        item.properties["publish_path"] = item.properties["path"]
        item.properties["publish_name"] = os.path.basename(item.properties["path"])[:-4]


        # Now that the path has been generated, hand it off to the
        super(MayaObjectGeometryUSDPublishPlugin, self).publish(settings, item)


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
    nodos.insert(0, node)
    breakFlag = False
    for i in nodos:
        if cmds.nodeType(i) == "transform":
            animAttributes = cmds.listAnimatable(i)
            for attribute in animAttributes:
                numKeyframes = cmds.keyframe(attribute, query=True, keyframeCount=True)
                if numKeyframes > 0:
                    breakFlag = True
                    break

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