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
import pprint
import traceback
from tank_vendor import six
import shutil


import sgtk
from sgtk.util.filesystem import copy_file, ensure_folder_exists

HookBaseClass = sgtk.get_hook_baseclass()

class RenderPublishPlugin(HookBaseClass):
    """
    Plugin for creating publishing renders
    """
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

        # inherit the settings from the base publish plugin
        plugin_settings = super(RenderPublishPlugin, self).settings or {}

        # settings specific to this class
        maya_render_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published renders. Should"
                "correspond to a template defined in "
                "templates.yml.",
            },
            "Link Local File": {
                "type": "bool",
                "default": True,
                "description": "Should the local file be referenced by Shotgun",
            },
        }

        # update the base settings
        plugin_settings.update(maya_render_publish_settings)

        return plugin_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """

        return ["maya.session.render"]

    def accept(self, settings, item):

        work_template = item.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "A work template is required for the session item in order to "
                "publish a render. Not accepting session render item."
            )
            return {"accepted": False}

        # ensure the publish template is defined and valid and that we also have
        publisher = self.parent
        publish_template_name = settings["Publish Template"].value
        publish_template = publisher.get_template_by_name(publish_template_name)
        if publish_template:
            item.properties["publish_template"] = publish_template
            # because a publish template is configured, disable context change.
            # This is a temporary measure until the publisher handles context
            # switching natively.
            item.context_change_allowed = False
        else:
            self.logger.debug(
                "The valid publish template could not be determined for the "
                "session render item. Not accepting the item."
            )
            return {"accepted": False}

        if publisher.context.step['name'] in ['LIGHT', 'LIGHT_A', 'TEXTURE_A']:
            return {"accepted": True, "checked": True}
        else:
            return {"accepted": True, "checked": False}
        
    def validate(self, settings, item):

        publisher = self.parent
        # get the configured work file template
        publish_template = item.properties.get("publish_template")

        work_fields = item.properties.get("work_fields")

        # ensure the fields work for the publish template
        missing_keys = publish_template.missing_keys(work_fields)
        # if len(missing_keys) != 1 or "frame_num" not in missing_keys:
        if missing_keys:
            error_msg = (
                "Work file '%s' missing keys required for the "
                "publish template: %s" % (item.properties["path"], missing_keys)
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # create the publish path by applying the fields. store it in the item's
        # properties. This is the path we'll create and then publish in the base
        # publish plugin. Also set the publish_path to be explicit.
        publish_path = publish_template.apply_fields(work_fields)
        item.properties["publish_path"] = publish_path.replace("6969", "####")
        number = '{0:03d}'.format(item.properties["publish_version"])
        rawversion = "_v" + str(number)
        item.properties["publish_name"] = self.get_publish_name(settings, item).replace(rawversion, '')
        publish_path = item.properties["publish_path"]
        publish_name = item.properties["publish_name"]

        # ---- check for conflicting publishes of this path with a status

        # Note the name, context, and path *must* match the values supplied to
        # register_publish in the publish phase in order for this to return an
        # accurate list of previous publishes of this file.
        publishes = publisher.util.get_conflicting_publishes(
            item.context,
            publish_path,
            publish_name,
            filters=["sg_status_list", "is_not", None],
        )

        if publishes:

            self.logger.debug(
                "Conflicting publishes: %s" % (pprint.pformat(publishes),)
            )



            if "work_template" in item.properties or publish_template:

                # templates are in play and there is already a publish in SG
                # for this file path. We will raise here to prevent this from
                # happening.
                error_msg = (
                    "Can not validate file path. There is already a publish in "
                    "Shotgun that matches this path. Please uncheck this "
                    "plugin or save the file to a different path."
                )
                self.logger.error(error_msg)
                raise Exception(error_msg)

            else:
                conflict_info = (
                        "If you continue, these conflicting publishes will no "
                        "longer be available to other users via the loader:<br>"
                        "<pre>%s</pre>" % (pprint.pformat(publishes),)
                )
                self.logger.warn(
                    "Found %s conflicting publishes in Shotgun" % (len(publishes),),
                    extra={
                        "action_show_more_info": {
                            "label": "Show Conflicts",
                            "tooltip": "Show conflicting publishes in Shotgun",
                            "text": conflict_info,
                        }
                    },
                )

        # TBR: revise if any parent class code is reusable
        # return super(PlayblastPublishPlugin, self).validate(settings, item)
        return super(RenderPublishPlugin, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        publisher = self.parent

        # ---- determine the information required to publish

        # We allow the information to be pre-populated by the collector or a
        # base class plugin. They may have more information than is available
        # here such as custom type or template settings.


        publish_type = item.properties["publish_type"]
        publish_version = item.properties["publish_version"]
        publish_path = item.properties.get("publish_path")
        publish_dependencies_paths = self.get_publish_dependencies(settings, item)
        publish_user = self.get_publish_user(settings, item)
        publish_fields = self.get_publish_fields(settings, item)
        # catch-all for any extra kwargs that should be passed to register_publish.
        publish_kwargs = self.get_publish_kwargs(settings, item)


        publish_name = item.properties["publish_name"]




        # if the parent item has publish data, get it id to include it in the list of
        # dependencies
        publish_dependencies_ids = []
        if "sg_publish_data" in item.parent.properties:
            publish_dependencies_ids.append(
                item.parent.properties.sg_publish_data["id"]
            )

        # handle copying of work to publish if templates are in play

        self._copy_work_to_publish(settings, item)

        # arguments for publish registration
        self.logger.info("Registering publish...")
        publish_data = {
            "tk": publisher.sgtk,
            "context": item.context,
            "comment": item.description,
            "path": publish_path,
            "name": publish_name,
            "created_by": publish_user,
            "version_number": publish_version,
            "thumbnail_path": item.get_thumbnail_as_path(),
            "published_file_type": publish_type,
            "dependency_paths": publish_dependencies_paths,
            "dependency_ids": publish_dependencies_ids,
            "sg_fields": publish_fields,
        }
        # add extra kwargs
        publish_data.update(publish_kwargs)

        # log the publish data for debugging
        self.logger.info(
            "Populated Publish data...",
            extra={
                "action_show_more_info": {
                    "label": "Publish Data",
                    "tooltip": "Show the complete Publish data dictionary",
                    "text": "<pre>%s</pre>" % (pprint.pformat(publish_data),),
                }
            },
        )

        # create the publish and stash it in the item properties for other
        # plugins to use.
        item.properties.sg_publish_data = sgtk.util.register_publish(**publish_data)
        self.logger.info("Publish registered!")
        self.logger.info(
            "Shotgun Publish data...",
            extra={
                "action_show_more_info": {
                    "label": "Shotgun Publish Data",
                    "tooltip": "Show the complete Shotgun Publish Entity dictionary",
                    "text": "<pre>%s</pre>"
                    % (pprint.pformat(item.properties.sg_publish_data),),
                }
            },
        )


        status = {"sg_status_list": "rev"}
        self.parent.sgtk.shotgun.update("Task", item.context.task['id'], status)


    def _copy_work_to_publish(self, settings, item):

        # if this is a sequence, get the attached files
        if "sequence_paths" in item.properties:
            work_files = item.properties.get("sequence_paths", [])
            self.logger.debug("work_files = %s", work_files)
            if not work_files:
                self.logger.warning(
                    "Sequence publish without a list of files. Publishing "
                    "the sequence path in place: %s" % (item.properties.path,)
                )
                return


        # ---- copy the work files to the publish location
        for work_file in work_files:

            publish_file = item.properties["publish_path"].replace("####", work_file.split(".")[-2])

            # copy the file
            try:
                self.logger.debug("Copying %s --> %s", work_file, publish_file)
                publish_folder = os.path.dirname(publish_file)
                ensure_folder_exists(publish_folder)
                workFileNorm = os.path.normpath(work_file)
                publishFileNorm = os.path.normpath(publish_file)
                # os.rename(workFileNorm, publishFileNorm)
                shutil.move(workFileNorm, publishFileNorm)
            except Exception:
                raise Exception(
                    "Failed to move work file from '%s' to '%s'.\n%s"
                    % (work_file, publish_file, traceback.format_exc())
                )

            self.logger.debug(
                "Moved work file '%s' to publish file '%s'."
                % (work_file, publish_file)
            )

