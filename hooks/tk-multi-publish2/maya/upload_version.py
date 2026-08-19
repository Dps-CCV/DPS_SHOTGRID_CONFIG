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
import glob
import pprint
import sgtk
from tank_vendor import six
import maya.mel as mel
import maya.cmds as cmds
import subprocess
import sys

HookBaseClass = sgtk.get_hook_baseclass()


class UploadVersionPlugin(HookBaseClass):
    """
    Plugin for sending quicktimes and images to shotgun for review.
    """

    @property
    def icon(self):
        """
        Path to an png icon on disk
        """

        # look for icon one level up from this hook's folder in "icons" folder
        return os.path.join(self.disk_location, "icons", "video.png")

    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Upload for review"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        publisher = self.parent

        shotgun_url = publisher.sgtk.shotgun_url

        media_page_url = "%s/page/media_center" % (shotgun_url,)
        review_url = "https://www.shotgridsoftware.com/features/#review"

        return """
        Upload the file to Flow Production Tracking for review.<br><br>

        A <b>Version</b> entry will be created in Flow Production Tracking and
        a transcoded copy of the file will be attached to it. The file can then
        be reviewed via the project's <a href='%s'>Media</a> page,
        <a href='%s'>RV</a>, or the <a href='%s'>Flow Production Tracking Review</a>
        mobile app.
        """ % (
            media_page_url,
            review_url,
            review_url,
        )

        # TODO: when settings editable, describe upload vs. link

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to recieve
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
        return {
            "File Extensions": {
                "type": "str",
                "default": "jpeg, jpg, png, mov, mp4, pdf, exr, avi, ma, mb",
                "description": "File Extensions of files to include",
            },
            "Upload": {
                "type": "bool",
                "default": True,
                "description": "Upload content to Flow Production Tracking?",
            },
            "Link Local File": {
                "type": "bool",
                "default": True,
                "description": "Should the local file be referenced by Shotgun",
            },
            "Dailies Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published dailies. Should"
                               "correspond to a template defined in "
                               "templates.yml.",
            },
            "Dailies Low Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published playblast. Should"
                               "correspond to a template defined in "
                               "templates.yml.",
            },
        }

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """

        # we use "video" since that's the mimetype category.
        return ["file.image", "file.video", "maya.session.playblast", "maya.session.playblastSeq", "maya.session.render", "maya.session"]

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

        publisher = self.parent
        path = item.properties["path"]

        # Accept any files with a valid extension defined in the setting "File Extensions"
        file_info = publisher.util.get_file_path_components(path)
        extension = file_info["extension"].lower()

        valid_extensions = []

        for ext in settings["File Extensions"].value.split(","):
            ext = ext.strip().lstrip(".")
            valid_extensions.append(ext)

        self.logger.debug("Valid extensions: %s" % valid_extensions)

        if item.type == "maya.session":
            template_name = settings["Dailies Low Template"].value
        elif item.type == "maya.session.render":
            template_name = settings["Dailies Template"].value
        dailies_template = publisher.get_template_by_name(template_name)
        item.properties["dailies_template"] = dailies_template

        if dailies_template:
            if extension in valid_extensions or item.type == "maya.session":
                # log the accepted file and display a button to reveal it in the fs
                self.logger.info(
                    "Version upload plugin accepted: %s" % (path,),
                    extra={"action_show_folder": {"path": path}},
                )

                # return the accepted info
                return {"accepted": True}

        else:
            self.logger.debug(
                "%s is not in the valid extensions list for Version creation"
                % (extension,)
            )
            return {"accepted": False}

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish.

        Returns a boolean to indicate validity.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: True if item is valid, False otherwise.
        """
        if self.get_dailies_path(settings, item) != None:
            item.properties["Dailies_path"] = self.get_dailies_path(settings, item)
            return True
        else:
            return False

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        publisher = self.parent
        uploadPath = item.properties["Dailies_path"]

        if "sequence_paths" in item.properties.keys() and item.type == "maya.session.render":


            first = item.properties['sequence_paths'][0][-8:-4]
            last = item.properties['sequence_paths'][-1][-8:-4]

            framerate = str(mel.eval('float $fps = `currentTimeUnitToFPS`'))
            start_number = first
            in_path = item.properties['publish_path'].replace("####", '%04d')
            in_sequence = in_path.replace('\\', '/')
            lut_path = r"L\:/NUKE_CONFIG/ACESCg_to_Rec709.cube"  # keep the backslash before the colon
            out_mov = uploadPath.replace('\\', '/')
            font_path = "C\:/Windows/Fonts/arial.ttf"
            Project = item.context.project['name']
            Entity = item.context.entity['name']
            Logo = os.path.join(self.disk_location, os.pardir, "icons", "EFCT_LOGO_v2.png")

            Project_esc = _escape_drawtext_text(Project)
            Entity_esc = _escape_drawtext_text(Entity)

            # Build the vf chain:
            vf_original = (
                "format=gbrpf32le,"
                f"lut3d='{lut_path}',"
                "scale=1920:1080,format=yuv422p10le"
            )

            # Build the vf chain:
            filter_complex = (
                f"[0:v]{vf_original}[base];"
                f"[base]"
                # Top-left: Project
                f"drawtext=fontfile='{font_path}':"
                f"text='{Project_esc}':"
                f"fontcolor=white:fontsize=36:x=20:y=20:"
                f"borderw=2:bordercolor=black@0.6,"

                # Bottom-left: Entity
                f"drawtext=fontfile='{font_path}':"
                f"text='{Entity_esc}':"
                f"fontcolor=white:fontsize=32:x=20:y=H-th-20:"
                f"borderw=2:bordercolor=black@0.6,"

                # Bottom-right: current (absolute) frame number = start_number + n
                # Note: escape colons inside eif with \\
                f"drawtext=fontfile='{font_path}':"
                f"text='%{{eif\\:n+{start_number}\\:d}}':"
                f"fontcolor=white:fontsize=32:x=W-tw-20:y=H-th-20:"
                f"borderw=2:bordercolor=black@0.6"
                f"[txt];"
                # Logo overlay on top-right (20px margin)
                # main W/H come from [txt]; overlay w/h come from [1:v]
                f"[txt][1:v]overlay=W-w-20:20:format=auto:eval=init"
            )


            # Assemble the final command with all quotes preserved
            cmd = (
                f'ffmpeg -framerate {framerate} -start_number {start_number} '
                f'-i "{in_sequence}" '
                f'-i "{Logo}" '          # logo image
                f'-filter_complex "{filter_complex}" '
                f'-c:v prores_ks -profile:v 3 -pix_fmt yuv422p10le '
                f'-movflags +write_colr -color_primaries bt709 -color_trc bt709 -colorspace bt709 '
                f'"{out_mov}"'
            )
            self.logger.info(cmd)
            self.logger.info(os.environ['PATH'])

            with subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1  # line-buffered
            ) as proc:
                for line in proc.stdout:
                    sys.stdout.write(line)  # stream to your console (or handle it as you like)
                    self.logger.info(line)
                return_code = proc.wait()

            print("Exit code:", return_code)

        elif item.type == "maya.session":

            # Create Playblast either by generating a turntable camera or using camMain



            '''En esta funcion chequeo que la estructura en la escena y del propia escena sea la correcta,
            es decir que contenga los nulls geo, basemesh debajo del nombre del asset'''

            ##Set First frame
            # first = cmds.playbackOptions(q=True, min=True)

            # Checking Root Structure
            # rootNodes = cmds.ls(assemblies=True)  # variable con la lista de objetos de la escena
            rootNodes = cmds.ls(o=True)  # variable con la lista de objetos de la escena
            maxKeyframe = 120
            minKeyframe = 0
            all_keys = []

            '''Se comprueba que solo exista un root null en la escena obviando las camaras'''

            cameras = cmds.listCameras()
            turntable = True
            for cam in cameras:
                if "camMain" in cam:
                    turntable = False
                    main = cam
                else:
                    try:
                        rootNodes.remove(cam)
                    except:
                        pass
            '''Compruebo que la estructura del root es correcta'''
            if len(rootNodes) == 0:
                error_msg = "Scene structure is incorrect. There is no root nodes."
                self.logger.error(error_msg)
                raise Exception(error_msg)

            else:

                # Check for animations
                anim = False
                for node in rootNodes:
                    all_keys = sorted(cmds.keyframe(node,
                                                    q=True) or [])  # Get all the keys and sort them by order. We use `or []` in-case it has no keys, which will use an empty list instead so it doesn't crash `sort`.
                    if len(all_keys) > 0:  # Check to see if it at least has one key.
                        anim = True
                        minKeyframe, maxKeyframe = (all_keys[0], all_keys[-1])  # Print the start and end frames
                        if all_keys[0] < minKeyframe:
                            minKeyframe = all_keys[0]
                        if all_keys[-1] > maxKeyframe:
                            maxKeyframe = all_keys[-1]

                # rootNode = cmds.listRelatives(rootNodes[0], fullPath=True)

                if turntable == True:
                    first = 0
                    ###Set last frame
                    last = maxKeyframe

                    ### Create camera turntable
                    obj = cmds.camera()
                    obj = cmds.rename(obj[0], "turnCam")
                    cmds.group(obj, name='rotGrp')

                    ## Select asset in scene
                    if anim:
                        first = minKeyframe
                        cmds.setAttr((obj + '.rotate'), -15, 0, 0, type="double3")
                        cmds.setAttr((obj + 'Shape.panZoomEnabled'), 1)
                        cmds.xform('rotGrp', ws=True, rp=[0, 0, 0])
                        cmds.setAttr((obj + 'Shape.zoom'), 1)
                        cmds.expression(s='rotGrp.rotateY = 45')
                        cmds.viewFit(obj, f=1)
                        cmds.setAttr((obj + 'Shape.farClipPlane'),
                                     (cmds.getAttr(obj + 'Shape.centerOfInterest') * 2))
                        ###Set last frame
                        cmds.playbackOptions(animationStartTime=first, animationEndTime=maxKeyframe, minTime=first,
                                             maxTime=maxKeyframe)
                    else:
                        cmds.setAttr((obj + '.rotate'), -15, 45, 0, type="double3")
                        cmds.setAttr((obj + 'Shape.panZoomEnabled'), 0)
                        cmds.xform('rotGrp', ws=True, rp=[0, 0, 0])
                        cmds.setAttr((obj + 'Shape.zoom'), 1)
                        cmds.expression(s='rotGrp.rotateY = frame * (360/120)')
                        cmds.viewFit(obj, f=1)
                        cmds.setAttr((obj + 'Shape.farClipPlane'),
                                     (cmds.getAttr(obj + 'Shape.centerOfInterest') * 2))
                        ###Set last frame
                        cmds.playbackOptions(animationStartTime=0, animationEndTime=maxKeyframe, minTime=0,
                                             maxTime=maxKeyframe)

                    cmds.lookThru(obj)

                else:
                    ##Set First frame
                    first = cmds.playbackOptions(q=True, min=True)
                    last = cmds.playbackOptions(q=True, max=True)
                    cmds.lookThru(main)
                    previousMaskOpacity = cmds.getAttr((main + '.displayGateMaskOpacity'))
                    previousAspectRatio = cmds.getAttr("defaultResolution.deviceAspectRatio")
                    previousOverscan = cmds.getAttr(main + ".overscan")
                    cmds.setAttr((main + '.displayGateMaskColor'), 0, 0, 0, type="double3")
                    cmds.setAttr((main + '.displayGateMaskOpacity'), 1)
                    cmds.setAttr((main + '.overscan'), 1.0)
                    proj = sgtk.platform.current_engine().shotgun.find_one('Project', [['name', 'is', item.context.project['name']]], ['sg_formato___ratio'])
                    cmds.setAttr("defaultResolution.deviceAspectRatio", round(float(proj['sg_formato___ratio']), 3))

                ## Process avi
                cmds.playblast(format='avi',
                               filename=uploadPath,
                               startTime=first,
                               endTime=last,
                               widthHeight=[1920, 1080],
                               sequenceTime=0,
                               clearCache=1,
                               viewer=0,
                               showOrnaments=1,
                               percent=100,
                               compression='none',
                               quality=100,
                               fo=1)

                if turntable == True:
                    cmds.delete('rotGrp')
                else:
                    cmds.setAttr((main + '.displayGateMaskOpacity'), previousMaskOpacity)
                    cmds.setAttr("defaultResolution.deviceAspectRatio", previousAspectRatio)
                    cmds.setAttr(main + ".overscan", previousOverscan)

        # use the path's filename as the publish name
        path_components = publisher.util.get_file_path_components(uploadPath)
        publish_name = path_components["filename"]

        self.logger.debug("Publish name: %s" % (publish_name,))

        self.logger.info("Creating Version...")
        version_data = {
            "project": item.context.project,
            "code": publish_name,
            "description": item.description,
            "entity": self._get_version_entity(item),
            "sg_task": item.context.task,
            "sg_first_frame": int(first),
            "sg_last_frame": int(last),
            "frame_count": int(int(last) - int(first)),
            "frame_range": str(first) + "-" + str(last),
        }

        if "sg_publish_data" in item.properties:
            publish_data = item.properties["sg_publish_data"]
            version_data["published_files"] = [publish_data]

            try:
                sg_parent_publish_data = item.parent.parent.properties.get("sg_publish_data")
                if sg_parent_publish_data is not None:
                    version_data["published_files"] = [publish_data, sg_parent_publish_data]
            except:
                self.logger.info("No parent publish data found")


        if settings["Link Local File"].value:
            version_data["sg_path_to_movie"] = uploadPath

        if item.type == "maya.session.render":
            version_data["sg_path_to_frames"] = item.properties["publish_path"]

        # log the version data for debugging
        self.logger.info(
            "Populated Version data...",
            extra={
                "action_show_more_info": {
                    "label": "Version Data",
                    "tooltip": "Show the complete Version data dictionary",
                    "text": "<pre>%s</pre>" % (pprint.pformat(version_data),),
                }
            },
        )

        # Create the version
        version = publisher.shotgun.create("Version", version_data)
        self.logger.info("Version created!")

        # stash the version info in the item just in case
        item.properties["sg_version_data"] = version

        thumb = item.get_thumbnail_as_path()

        self.logger.info("Uploading content...")

        # on windows, ensure the path is utf-8 encoded to avoid issues with
        # the shotgun api

        if sgtk.util.is_windows():
            upload_path = six.ensure_text(uploadPath)
        else:
            upload_path = uploadPath

        self.parent.shotgun.upload(
            "Version", version["id"], upload_path, "sg_uploaded_movie"
        )

        self.logger.info("Upload complete!")




    def finalize(self, settings, item):
        """
        Execute the finalization pass. This pass executes once all the publish
        tasks have completed, and can for example be used to version up files.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        path = item.properties["sg_version_data"]["sg_path_to_movie"]
        version = item.properties["sg_version_data"]

        self.logger.info(
            "Version uploaded for file: %s" % (path,),
            extra={
                "action_show_in_shotgun": {
                    "label": "Show Version",
                    "tooltip": "Reveal the version in Shotgun.",
                    "entity": version,
                }
            },
        )

    def _get_version_entity(self, item):
        """
        Returns the best entity to link the version to.
        """

        if item.context.entity:
            return item.context.entity
        elif item.context.project:
            return item.context.project
        else:
            return None


    def get_dailies_path(self, settings, item):
        """
        Get a publish path for the supplied settings and item.

        :param settings: This plugin instance's configured settings
        :param item: The item to determine the publish path for

        :return: A string representing the output path to supply when
            registering a publish for the supplied item

        Extracts the publish path via the configured work and publish templates
        if possible.
        """



        # fall back to template/path logic
        path = _session_path()
        work_template = item.properties.get("work_template")
        dailies_template = item.properties["dailies_template"]



        work_fields = []
        dailies_path = None

        # We need both work and publish template to be defined for template
        # support to be enabled.
        if work_template and dailies_template:

            if work_template.validate(path):
                work_fields = work_template.get_fields(path)
                if item.type == "maya.session":
                    work_fields["extension"] = "avi"
                elif item.type == "maya.session.render":
                    work_fields["maya.layer_name"] = item.properties["maya.layer_name"]
                    work_fields["extension"] = "mov"


            missing_keys = dailies_template.missing_keys(work_fields)


            if missing_keys:
                self.logger.warning(
                    "Not enough keys to apply work fields (%s) to "
                    "publish template (%s)" % (work_fields, dailies_template)
                )
            else:
                dailies_path = dailies_template.apply_fields(work_fields)
                self.logger.debug(
                    "Used publish template to determine the publish path: %s"
                    % (dailies_path,)
                )
        else:
            self.logger.debug("dailies_template: %s" % dailies_template)
            self.logger.debug("work_template: %s" % work_template)


        return dailies_path

def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = cmds.file(query=True, sn=True)

    if path is not None:
        path = six.ensure_str(path)

    return path


def _escape_drawtext_text(s: str) -> str:
    """
    Escape a Python string for safe use inside FFmpeg drawtext text='...'.
    - Escape backslashes and single quotes.
    - Leave ffmpeg expression placeholders like %{...} alone if you pass them as raw strings.
    """
    return s.replace("\\", "\\\\").replace("'", r"\'")