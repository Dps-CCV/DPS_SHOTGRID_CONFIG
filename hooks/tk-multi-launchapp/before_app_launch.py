# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Before App Launch Hook

This hook is executed prior to application launch and is useful if you need
to set environment variables or run scripts as part of the app initialization.
"""

import os
import tank
import sys
import argparse



class BeforeAppLaunch(tank.Hook):

    # --------------------------------------------------------------------------
    # Helpers: find latest .basic.desktop folder and rebuild path
    # --------------------------------------------------------------------------

    def _find_project_level(self, path_parts, marker=".basic.desktop"):
        """
        Returns the index in path_parts where the folder containing marker is found.
        E.g. for ['L:\\', 'SHOTGUN_CACHE', 'dareplanet', 'p7283c2542.basic.desktop', ...]
        returns 3.
        """
        for i, part in enumerate(path_parts):
            if marker in part:
                return i
        return -1

    def _get_latest_desktop_folder(self, parent_dir, marker=".basic.desktop"):
        """
        Scans parent_dir for subdirectories containing marker and returns
        the name of the most recently modified one, or None if none found.
        """
        if not os.path.isdir(parent_dir):
            raise FileNotFoundError("Parent directory does not exist: {}".format(parent_dir))

        candidates = []
        try:
            entries = os.scandir(parent_dir)
        except PermissionError as e:
            raise PermissionError("No permission to read: {}".format(parent_dir)) from e

        for entry in entries:
            if entry.is_dir() and marker in entry.name:
                try:
                    candidates.append((entry.name, entry.stat().st_mtime))
                except OSError:
                    pass

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def rebuild_path(self, original_path, marker=".basic.desktop"):
        """
        Given a full path, finds the segment containing marker, locates the
        most recently modified folder with that marker in the same parent
        directory, and returns the fully reconstructed path.

        :param original_path: Full original path, e.g.:
            'L:\\SHOTGUN_CACHE\\dareplanet\\p7283c2542.basic.desktop\\cfg\\install\\core\\python'
        :param marker: String that identifies the project cache folder (default: '.basic.desktop')
        :returns: Reconstructed path with the latest folder substituted in.
        :raises ValueError: If no folder with marker is found in the path.
        :raises FileNotFoundError: If the parent directory does not exist.
        """
        original_path = os.path.normpath(original_path)

        # Split path into individual parts
        parts = []
        head = original_path
        while True:
            head, tail = os.path.split(head)
            if tail:
                parts.insert(0, tail)
            elif head:
                parts.insert(0, head)
                break
            else:
                break

        marker_index = self._find_project_level(parts, marker)
        if marker_index == -1:
            raise ValueError(
                "No folder with '{}' found in path: {}".format(marker, original_path)
            )

        # Reconstruct parent dir (everything before the marker segment)
        parent_dir = os.path.join(*parts[:marker_index])
        if not os.path.isabs(parent_dir):
            parent_dir = parts[0] + os.sep + os.path.join(*parts[1:marker_index])

        latest_folder = self._get_latest_desktop_folder(parent_dir, marker)
        if latest_folder is None:
            raise FileNotFoundError(
                "No folder with '{}' found in: {}".format(marker, parent_dir)
            )

        suffix_parts = parts[marker_index + 1:]
        new_parts = parts[:marker_index] + [latest_folder] + suffix_parts
        return os.path.join(*new_parts)

    """
    Hook to set up the system prior to app launch.
    """

    def execute(
        self, app_path, app_args, version, engine_name, software_entity=None, **kwargs
    ):
        """
        The execute function of the hook will be called prior to starting the required application

        :param app_path: (str) The path of the application executable
        :param app_args: (str) Any arguments the application may require
        :param version: (str) version of the application being run if set in the
            "versions" settings of the Launcher instance, otherwise None
        :param engine_name (str) The name of the engine associated with the
            software about to be launched.
        :param software_entity: (dict) If set, this is the Software entity that is
            associated with this launch command.

        Additional references
            https://developer.shotgunsoftware.com/624f2593/
        """

        # accessing the current context (current shot, etc)
        # can be done via the parent object
        #
        # > multi_launchapp = self.parent
        # > current_entity = multi_launchapp.context.entity

        # you can set environment variables like this:
        # os.environ["MY_SETTING"] = "foo bar"

        ## Acceder al contexto
        multi_launchapp = self.parent
        current_context = multi_launchapp.context


        ## Definir variables generales para su posible uso posterior dentro de las aplicaciones
        os.environ["PROJECT"] = str(current_context.project["name"])
        os.environ["ARTIST"] = current_context.user["name"]
        project_path = self.parent.tank.roots.get("primary")

        os.environ["PROJECT_PATH"] = project_path
        rawMount = os.path.normpath(project_path)
        Mount = rawMount.split(os.sep)[0]
        os.environ["MOUNT"] = Mount
        ocio_path = os.path.join(
            project_path, "CONFIG", "COLOR", "ACES", "studio-config-v1.0.0_aces-v1.3_ocio-v2.1.ocio"
        )
        os.environ["OCIO"] = ocio_path

        getColor = tank.platform.current_engine().shotgun.find_one("Project", [["name", "is", str(current_context.project["name"])]], ["code", "sg_espacio___color", "sg_format", "sg_compression", "sg_formato___ratio", "sg_channels"])

        os.environ["PROJECTCOLORSPACE"] = str(getColor["sg_espacio___color"])

        os.environ["FormExt"] = getColor['sg_format']
        # if getColor['sg_format'] == 'exr':
        #     os.environ["CompressionExt"] = getColor['sg_compression']
        # else:
        #     os.environ["CompressionExt"] = getColor['sg_format']

        os.environ["COMPRESSION"] = str(getColor["sg_compression"])
        os.environ["CHANNELS"] = str(getColor["sg_channels"])



        os.environ["PROJECTMASK"] = str(getColor["sg_formato___ratio"])

        # os.environ["RV_SUPPORT_PATH"] = os.path.join(project_path, "CONFIG", "COLOR", "RV")


        os.environ["PROJECT_CODE"] = str(getColor["code"])

        os.environ['RV_USE_CUTS_IN_SCREENING_ROOM'] = "1"

        os.environ['RV_CUSTOM_MATTE_DEFINITIONS'] = os.path.join(project_path, "CONFIG", "COLOR", "RV", "SupportFiles", "custom_mattes")

        os.environ['HOUDINI_ACCESS_METHOD'] = "2"

        os.environ['RV_USE_CUTS_IN_SCREENING_ROOM'] = "True"


        os.environ['SHOTGUN_SITE'] = tank.platform.current_engine().sgtk.shotgun_url

        os.environ['SHOTGUN_CONFIG_URI'] = tank.platform.current_engine().sgtk.configuration_descriptor.get_uri()
        os.environ['SHOTGUN_SGTK_MODULE_PATH'] = self.rebuild_path(tank.get_sgtk_module_path().replace('C:', 'L:'))

        ###Empty variables from clip and lmt. Later they are set at context change
        os.environ["CLIP"] = " "
        os.environ["LMT"] = " "
        os.environ["SHOT"] = " "

        ###Variables para Davinci Resolve
        os.environ[
            'RESOLVE_SCRIPT_API'] = "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting"
        os.environ['RESOLVE_SCRIPT_LIB'] = "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\fusionscript.dll"
        sys.path.append("C:\\ProgramData\\Blackmagic Design\\Support\\Developer\\Scripting\\Modules")
        tank.util.append_path_to_env_var("PYTHONPATH",
                                         "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules")

        ## Definir variables especificas de cada aplicacion
        if engine_name == "tk-maya":

            # desconectado test
            render_environ_path = os.path.abspath(os.path.join(
                project_path, "CONFIG/MAYA/render_settings/"
            ))
            renderTemplate_environ_path = os.path.abspath(os.path.join(
                project_path, "CONFIG/MAYA/RSTemplates/"
            ))
            os.environ["MAYA_RENDER_SETUP_GLOBAL_TEMPLATE_PATH"] = renderTemplate_environ_path
            os.environ["MAYA_RENDER_SETUP_GLOBAL_PRESETS_PATH"] = render_environ_path

            color_environ_path = os.path.abspath(os.path.join(
                project_path, "CONFIG/MAYA/color_prefs.xml"
            ))
            os.environ["MAYA_COLOR_MANAGEMENT_POLICY_FILE"] = color_environ_path
            #os.environ["MAYA_COLOR_MANAGEMENT_POLICY_LOCK"] = "1"

            os.environ["BIFROST_LIB_CONFIG_FILES"] = 'L:\\MAYA_ASSETS\\BiphostGraphs\\DarePlanetConfigurations.json'

            sys.path.append("L:\\MAYA_SCRIPTS\\PYTHON\\DF")
            sys.path.append("L:\\MAYA_SCRIPTS\\MEL\\DF")

            os.environ['MAYA_SCRIPT_PATH'] += ";" + "L:\\MAYA_SCRIPTS\\PYTHON\\DF" + ";" + "L:\\MAYA_SCRIPTS\\MEL\\DF"



        elif engine_name == "tk-nuke":
            # tank.util.append_path_to_env_var("NUKE_PATH", 'L:\\NUKE_CONFIG')
            ##Variables de Nuke
            nuke_environ_path = os.path.join(
                project_path, "CONFIG/NUKE"
            )
            tank.util.append_path_to_env_var("NUKE_PATH", nuke_environ_path)

            os.environ['NUKE_INSTALL'] = str(app_path)



        elif engine_name == "tk-hiero" or engine_name == "tk-nukestudio":
            # hieroPlugin_environ_path = "L:\\HIERO_PLUGIN_PATH"
            # tank.util.append_path_to_env_var("HIERO_PLUGIN_PATH", hieroPlugin_environ_path)
            nuke_environ_path = os.path.join(
                project_path, "CONFIG/NUKE"
            )
            tank.util.append_path_to_env_var("NUKE_PATH", nuke_environ_path)

            os.environ['NUKE_INSTALL'] = str(app_path)


        # elif engine_name == "tk-houdini":
        #     folder = "Houdini " + version
            # houdini_environ_path = os.path.abspath(os.path.join(
            #     project_path, "CONFIG/HOUDINI/", folder
            # ))
            # os.environ['HOUDINI_USER_PREF_DIR'] = houdini_environ_path
            #houdini_dps_plugins_path = os.path.abspath(os.path.join(
            #     os.environ['CONFIG_FOLDER'], "bundles", "CONFIG/HOUDINI/", folder
            # ))
            # os.environ['HOUDINI_USER_PREF_DIR'] = "L:\\HOUDINI_CONFIG\\Houdini 19.5.435"
            # os.environ['HOUDINI_DPS_PLUGINS'] = houdini_dps_plugins_path

            # self.logger.info("Test %s", houdini_environ_path)








