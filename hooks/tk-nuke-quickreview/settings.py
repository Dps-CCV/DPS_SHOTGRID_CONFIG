# Copyright (c) 2017 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import sgtk
import sys
import os
import nuke
import datetime

from tank_vendor import six

HookBaseClass = sgtk.get_hook_baseclass()


class Settings(HookBaseClass):
    """
    Controls various review settings and formatting.
    """

    def get_burnins_and_slate(self, sg_version_name, context):
        """
        Return the burnins that should be used for the quicktime.

        :param str sg_version_name: The name of the shotgun review version
        :param context: The context associated with the version.
        :returns: Dictionary with burn-ins and slate strings
        """
        return_data = {}

        # current user
        user_data = sgtk.util.get_current_user(self.parent.sgtk)
        if user_data is None:
            user_name = "Unknown User"
        else:
            user_name = user_data.get("name", "Unknown User")

        # top-left says
        # Project XYZ
        # Shot ABC
        top_left = "%s" % context.project["name"]
        if context.entity:
            top_left += "\n%s %s" % (context.entity["type"], context.entity["name"])
        return_data["top_left"] = top_left

        # top-right has date
        # The format '23 Jan 2012' is universally understood.
        today = datetime.date.today()
        date_formatted = today.strftime("%d %b %Y")
        return_data["top_right"] = date_formatted

        # bottom left says
        # sg version name
        # User
        bottom_left = "%s\n%s" % (sg_version_name, user_name)
        return_data["bottom_left"] = bottom_left

        # and format the slate
        slate_items = []
        slate_items.append("Project: %s" % context.project["name"])
        if context.entity:
            slate_items.append("%s: %s" % (context.entity["type"], context.entity["name"]))
        slate_items.append("Name: %s" % sg_version_name)

        if context.task:
            slate_items.append("Task: %s" % context.task["name"])
        elif context.step:
            slate_items.append("Step: %s" % context.step["name"])

        slate_items.append("Date: %s" % date_formatted)
        slate_items.append("User: %s" % user_name)

        return_data["slate"] = slate_items

        return return_data

    def get_title(self, context):
        """
        Returns the title that should be used for the version

        :param context: The context associated with the version.
        :returns: Version title string.
        """
        # rather than doing a version numbering scheme, which we
        # reserve for publishing workflows, the default implementation
        # uses a date and time based naming scheme

        sg_version_name = ""

        # include the shot/link as part of the name
        # if context.entity and context.entity["name"]:
        #     # start with the link
        #     sg_version_name += "[%s %s] " % (
        #         context.entity["type"],
        #         context.entity["name"]
        #     )

        # default name in case no nuke file name is set
        name = "Quickreview"

        # now try to see if we are in a normal work file
        # in that case deduce the name from it
        current_scene_path = nuke.root().name()
        current_scene_path = six.ensure_str(current_scene_path)

        if current_scene_path and current_scene_path != "Root":
            current_scene_path = current_scene_path.replace("/", os.path.sep)
            # get just filename
            current_scene_name = os.path.basename(current_scene_path)
            # drop .nk
            current_scene_name = os.path.splitext(current_scene_name)[0]
            name = current_scene_name.replace("_", " ").capitalize()

        sg_version_name += name

        # append date and time
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        sg_version_name += ", %s" % timestamp

        return sg_version_name

    def get_resolution(self):
        """
        Returns the resolution that should be used when rendering the quicktime.

        :returns: tuple with (width, height)
        """
        return 1920, 1080

    def setup_quicktime_node(self, write_node):
        """
        Allows modifying settings for Quicktime generation.

        :param write_node: The nuke write node used to generate the quicktime that is being uploaded.
        """
        input_node = write_node.input(0)
        parent_group = write_node.parent()
        with parent_group:
            look = nuke.createNode("OCIOLookTransform")
            look.setInput(0, input_node)
            look.knob("look").setValue("SHOT_GRADE")
        write_node["file_type"].setValue("mov")
        write_node["mov64_codec"].setValue("AVdn")
        write_node["mov64_quality_max"].setValue("3")
        write_node["mov_h264_codec_profile"].setValue("High 4:2:0 8-bit")
        write_node["mov64_quality"].setValue("High")
        write_node["mov64_write_timecode"].setValue(1)
        write_node["colorspace"].setValue("Output - Rec.709")
        write_node["fps"].setValue(nuke.root()['fps'].value())
        write_node.setInput(0, look)

