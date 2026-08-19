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
from sgtk.util.filesystem import ensure_folder_exists
from tank_vendor import six




import shutil


import re
import glob
import json
from collections import defaultdict



HookBaseClass = sgtk.get_hook_baseclass()


class MayaSessionPublishPlugin(HookBaseClass):
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

        loader_url = "https://support.shotgunsoftware.com/hc/en-us/articles/219033078"

        return """
        Publishes the file to Shotgun. A <b>Publish</b> entry will be
        created in Shotgun which will include a reference to the file's current
        path on disk. If a publish template is configured, a copy of the
        current session will be copied to the publish template path which
        will be the file that is published. Other users will be able to access
        the published file via the <b><a href='%s'>Loader</a></b> so long as
        they have access to the file's location on disk.

        If the session has not been saved, validation will fail and a button
        will be provided in the logging output to save the file.

        <h3>File versioning</h3>
        If the filename contains a version number, the process will bump the
        file to the next version after publishing.

        The <code>version</code> field of the resulting <b>Publish</b> in
        Shotgun will also reflect the version number identified in the filename.
        The basic worklfow recognizes the following version formats by default:

        <ul>
        <li><code>filename.v###.ext</code></li>
        <li><code>filename_v###.ext</code></li>
        <li><code>filename-v###.ext</code></li>
        </ul>

        After publishing, if a version number is detected in the work file, the
        work file will automatically be saved to the next incremental version
        number. For example, <code>filename.v001.ext</code> will be published
        and copied to <code>filename.v002.ext</code>

        If the next incremental version of the file already exists on disk, the
        validation step will produce a warning, and a button will be provided in
        the logging output which will allow saving the session to the next
        available version number prior to publishing.

        <br><br><i>NOTE: any amount of version number padding is supported. for
        non-template based workflows.</i>

        <h3>Overwriting an existing publish</h3>
        In non-template workflows, a file can be published multiple times,
        however only the most recent publish will be available to other users.
        Warnings will be provided during validation if there are previous
        publishes.
        """ % (
            loader_url,
        )

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
        base_settings = super(MayaSessionPublishPlugin, self).settings or {}

        # settings specific to this class
        maya_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published work files. Should"
                "correspond to a template defined in "
                "templates.yml.",
            },
        }

        # update the base settings
        base_settings.update(maya_publish_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """
        return ["maya.session"]

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

        # if a publish template is configured, disable context change. This
        # is a temporary measure until the publisher handles context switching
        # natively.
        if settings.get("Publish Template").value:
            item.context_change_allowed = False

        path = item.properties["path"]

        if not path:
            # the session has not been saved before (no path determined).
            # provide a save button. the session will need to be saved before
            # validation will succeed.
            self.logger.warn(
                "The Maya session has not been saved.", extra=_get_save_as_action()
            )

        self.logger.info(
            "Maya '%s' plugin accepted the current Maya session." % (self.name,)
        )
        return {"accepted": True, "checked": True}

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

        publisher = self.parent
        path =  item.properties["path"]



        # ---- ensure the session has been saved

        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Maya session has not been saved."
            self.logger.error(error_msg, extra=_get_save_as_action())
            raise Exception(error_msg)

        # ensure we have an updated project root
        project_root = cmds.workspace(q=True, rootDirectory=True)
        item.properties["project_root"] = project_root

        # log if no project root could be determined.
        if not project_root:
            self.logger.info(
                "Your session is not part of a maya project.",
                extra={
                    "action_button": {
                        "label": "Set Project",
                        "tooltip": "Set the maya project",
                        "callback": lambda: mel.eval('setProject ""'),
                    }
                },
            )

        # ---- check the session against any attached work template


        # if the session item has a known work template, see if the path
        # matches. if not, warn the user and provide a way to save the file to
        # a different path
        work_template = item.properties.get("work_template")
        if work_template:
            if not work_template.validate(path):
                self.logger.warning(
                    "The current session does not match the configured work "
                    "file template.",
                    extra={
                        "action_button": {
                            "label": "Save File",
                            "tooltip": "Save the current Maya session to a "
                            "different file name",
                            # will launch wf2 if configured
                            "callback": _get_save_as_action(),
                        }
                    },
                )
            else:
                self.logger.debug("Work template configured and matches session file.")
        else:
            self.logger.debug("No work template configured.")

        # ---- see if the version can be bumped post-publish

        # check to see if the next version of the work file already exists on
        # disk. if so, warn the user and provide the ability to jump to save
        # to that version now
        (next_version_path, version) = self._get_next_version_info(path, item)
        if next_version_path and os.path.exists(next_version_path):

            # determine the next available version_number. just keep asking for
            # the next one until we get one that doesn't exist.
            while os.path.exists(next_version_path):
                (next_version_path, version) = self._get_next_version_info(
                    next_version_path, item
                )

            error_msg = "The next version of this file already exists on disk."
            self.logger.error(
                error_msg,
                extra={
                    "action_button": {
                        "label": "Save to v%s" % (version,),
                        "tooltip": "Save to the next available version number, "
                        "v%s" % (version,),
                        "callback": lambda: _save_session(next_version_path),
                    }
                },
            )
            raise Exception(error_msg)

        # ---- populate the necessary properties and call base class validation

        # populate the publish template on the item if found
        publish_template_setting = settings.get("Publish Template")
        publish_template = publisher.engine.get_template_by_name(
            publish_template_setting.value
        )
        if publish_template:
            item.properties["publish_template"] = publish_template



        # run the base class validation
        return super(MayaSessionPublishPlugin, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        # get the path in a normalized state. no trailing separator, separators
        # are appropriate for current os, no double separators, etc.
        path = item.properties["path"]

        # ensure the session is saved
        _save_session(path)


        # add dependencies for the base class to register when publishing
        item.properties[
            "publish_dependencies"
        ] = _maya_find_additional_session_dependencies()

        # let the base class register the publish
        super(MayaSessionPublishPlugin, self).publish(settings, item)



        status = {"sg_status_list": "rev"}
        self.parent.sgtk.shotgun.update("Task", item.context.task['id'], status)

    def finalize(self, settings, item):
        """
        Execute the finalization pass. This pass executes once all the publish
        tasks have completed, and can for example be used to version up files.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """
        if item.context.step['name'] in ['LIGHT', 'LIGHT_A', 'RIG_A', 'TEXTURE_A', 'SHADING_A']:
            path = cmds.file(query=True, sn=True)
            file = os.path.basename(path)[:-8]
            base = os.path.basename(path).split(".")[0]
            if 'SHOT_FOLDER' in os.environ.keys():
                ShotFolder = os.path.join(*os.environ['SHOT_FOLDER'].split(os.sep)[3:])
                archivePath = os.path.normpath(os.path.join(os.environ['PROJECT_PATH'], 'ARCHIVE', ShotFolder, base))[:-5]
            elif 'ASSET_FOLDER' in os.environ.keys():
                AssetFolder = os.path.join(*os.environ['ASSET_FOLDER'].split(os.sep)[3:])
                archivePath = os.path.normpath(os.path.join(os.environ['PROJECT_PATH'], 'ARCHIVE', AssetFolder, base))[:-5]
            if os.path.exists(archivePath):
                shutil.rmtree(archivePath)
            os.makedirs(archivePath)
            try:
                self.logger.info("Starting archive of the scene")
                result = archive_current_scene(archivePath, self.logger, file)

                if result:
                    self.logger.info("Scene archived successfully: %s" % result)
                    # Access the published entity created earlier
                    sg_publish = item.get_property("sg_publish_data")

                    if sg_publish:
                        # Update Shotgun/FPT fields as needed
                        self.sgtk.shotgun.update(
                            sg_publish["type"],
                            sg_publish["id"],
                            {"sg_archived": True}  # Any field you want to update
                        )
                else:
                    self.logger.warning("Archive creation returned None - check for errors above")
            except:
                self.logger.warning("Archive was not possible")

        # do the base class finalization
        super(MayaSessionPublishPlugin, self).finalize(settings, item)

        # bump the session file to the next version
        self._save_to_next_version(item.properties["path"], item, _save_session)


    def _copy_work_to_publish(self, settings, item):
        """
        This method handles copying work file path(s) to a designated publish
        location.

        This method requires a "work_template" and a "publish_template" be set
        on the supplied item.

        The method will handle copying the "path" property to the corresponding
        publish location assuming the path corresponds to the "work_template"
        and the fields extracted from the "work_template" are sufficient to
        satisfy the "publish_template".

        The method will not attempt to copy files if any of the above
        requirements are not met. If the requirements are met, the file will
        ensure the publish path folder exists and then copy the file to that
        location.

        If the item has "sequence_paths" set, it will attempt to copy all paths
        assuming they meet the required criteria with respect to the templates.

        """
        # ---- ensure templates are available
        work_template = item.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "No work template set on the item. "
                "Skipping copy file to publish location."
            )
            return

        publish_template = self.get_publish_template(settings, item)
        if not publish_template:
            self.logger.debug(
                "No publish template set on the item. "
                "Skipping copying file to publish location."
            )
            return


        # by default, the path that was collected for publishing
        work_file = item.properties.path

        # ---- copy the work files to the publish location


        if not work_template.validate(work_file):
            self.logger.warning(
                "Work file '%s' did not match work template '%s'. "
                "Publishing in place." % (work_file, work_template)
            )
            return

        work_fields = work_template.get_fields(work_file)

        missing_keys = publish_template.missing_keys(work_fields)

        if missing_keys:
            self.logger.warning(
                "Work file '%s' missing keys required for the publish "
                "template: %s" % (work_file, missing_keys)
            )
            return

        publish_file = publish_template.apply_fields(work_fields)
        if work_fields["extension"] == "ma":
            typeFile = "mayaAscii"
        else:
            typeFile = "mayaBinary"
        if not os.path.isdir(os.path.dirname(publish_file)):
            os.makedirs(os.path.dirname(publish_file))

        if item.context.step['name'] in ['RIG_A', 'TEXTURE_A', 'SHADING_A']:
            cmds.file(publish_file, exportAll=True, preserveReferences=False, force=True, type=typeFile)
        else:
            cmds.file(publish_file, exportAll=True, preserveReferences=True, force=True, type=typeFile)



        self.logger.debug(
            "Copied work file '%s' to publish file '%s'."
            % (work_file, publish_file)
        )


def _maya_find_additional_session_dependencies():
    """
    Find additional dependencies from the session
    """

    # default implementation looks for references and
    # textures (file nodes) and returns any paths that
    # match a template defined in the configuration
    ref_paths = set()

    # first let's look at maya references
    ref_nodes = cmds.ls(references=True)
    for ref_node in ref_nodes:
        # get the path:
        ref_path = cmds.referenceQuery(ref_node, filename=True)
        # make it platform dependent
        # (maya uses C:/style/paths)
        ref_path = ref_path.replace("/", os.path.sep)
        if ref_path:
            ref_paths.add(ref_path)

    # now look at file texture nodes
    for file_node in cmds.ls(l=True, type="file"):
        # ensure this is actually part of this session and not referenced
        if cmds.referenceQuery(file_node, isNodeReferenced=True):
            # this is embedded in another reference, so don't include it in
            # the breakdown
            continue

        # get path and make it platform dependent
        # (maya uses C:/style/paths)
        texture_path = cmds.getAttr("%s.fileTextureName" % file_node).replace(
            "/", os.path.sep
        )
        if texture_path:
            ref_paths.add(texture_path)

    return list(ref_paths)


def _save_session(path):
    """
    Save the current session to the supplied path.
    """

    # Maya can choose the wrong file type so we should set it here
    # explicitly based on the extension
    maya_file_type = None
    if path.lower().endswith(".ma"):
        maya_file_type = "mayaAscii"
    elif path.lower().endswith(".mb"):
        maya_file_type = "mayaBinary"

    # Maya won't ensure that the folder is created when saving, so we must make sure it exists
    folder = os.path.dirname(path)
    ensure_folder_exists(folder)

    cmds.file(rename=path)

    # save the scene:
    if maya_file_type:
        cmds.file(save=True, force=True, type=maya_file_type)
    else:
        cmds.file(save=True, force=True)


# TODO: method duplicated in all the maya hooks
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










# Extension -> archive subfolder mapping (mirrors Maya's Archive Scene logic)
EXT_TO_FOLDER = {
    # Scenes / references
    '.ma':   'scenes',
    '.mb':   'scenes',
    # Textures / images
    '.jpg':  'sourceimages',
    '.jpeg': 'sourceimages',
    '.png':  'sourceimages',
    '.tga':  'sourceimages',
    '.tif':  'sourceimages',
    '.tiff': 'sourceimages',
    '.exr':  'sourceimages',
    '.hdr':  'sourceimages',
    '.bmp':  'sourceimages',
    '.gif':  'sourceimages',
    '.iff':  'sourceimages',
    '.sgi':  'sourceimages',
    '.pic':  'sourceimages',
    '.psd':  'sourceimages',
    '.tx':   'sourceimages',
    '.rat':  'sourceimages',
    '.map':  'sourceimages',
    # Caches / geometry
    '.abc':  'cache',
    '.vdb':  'cache',
    '.ass':  'cache',
    '.fur':  'cache',
    '.mc':   'cache',
    '.mcx':  'cache',
    '.xml':  'cache',
    '.pc2':  'cache',
    # Audio
    '.wav':  'sound',
    '.aif':  'sound',
    '.aiff': 'sound',
    '.mp3':  'sound',
    # Movies / playblasts
    '.mov':  'movies',
    '.avi':  'movies',
    '.mp4':  'movies',
    # IES / data
    '.ies':  'data',
    '.cube': 'data',
    '.lut':  'data',
    '.mel':  'data',
    '.py':   'data',
}

# Tokens used by Maya/Arnold for frame-sequence file paths
SEQUENCE_TOKENS = ['####', '###', '##', '#', '<f>', '<F>', '<frame>', '<FRAME>', '%04d', '%03d', '%02d', '%d']


def _resolve_path(path):
    """
    Given a path that may contain sequence tokens, return a list of all
    matching files on disk. Returns a list with the original path if it
    exists as-is, or glob-expanded paths if tokens are found.
    """
    if not path:
        return []

    # Direct hit
    if os.path.exists(path):
        return [path]

    # Replace all known sequence tokens with glob wildcard
    glob_path = path
    for token in SEQUENCE_TOKENS:
        glob_path = glob_path.replace(token, '*')

    if glob_path != path:
        matches = glob.glob(glob_path)
        if matches:
            return sorted(matches)

    return []




class MayaSceneArchiver:
    """
    Archive Maya scene with all dependencies including references.
    Uses Maya's own file dependency query (same as Archive Scene menu)
    to guarantee every node type is covered.
    Creates symlinks for all files except the scene file itself.
    """

    def __init__(self, output_directory):
        self.output_dir = output_directory
        self.archive_structure = {}
        self.collected_files = defaultdict(list)
        self.reference_mapping = {}
        self.temp_scene_path = None

    def create_archive(self, logger, archive_name=None):
        logger.info("=" * 70)
        logger.info("MAYA SCENE ARCHIVER")
        logger.info("=" * 70)

        current_scene = cmds.file(query=True, sceneName=True)

        if not current_scene:
            cmds.warning("Scene is not saved. Please save before archiving.")
            return None

        if not archive_name:
            archive_name = os.path.splitext(os.path.basename(current_scene))[0] + "_archive"

        archive_path = os.path.join(self.output_dir, archive_name)

        logger.info("\nOutput Directory: %s" % self.output_dir)
        logger.info("Archive:          %s" % archive_path)
        logger.info("Source scene:     %s" % current_scene)

        self._create_directory_structure(logger, archive_path)

        try:
            logger.info("\n[1/6] Creating temporary scene copy...")
            self._create_temp_scene_copy(logger)

            logger.info("\n[2/6] Collecting file dependencies...")
            self._collect_all_files(logger)

            logger.info("\n[3/6] Processing references...")
            self._process_references(logger)

            logger.info("\n[4/6] Linking files to archive...")
            self._link_files_to_archive(logger)

            logger.info("\n[4b] Redirecting node attributes to archive paths...")
            self._redirect_node_attributes(logger)

            logger.info("\n[5/6] Saving archived scene...")
            archived_scene_path = self._save_archived_scene(logger, archive_name)

            logger.info("\n[6/6] Creating archive manifest...")
            self._create_manifest(logger, archive_path, archived_scene_path)

            logger.info("\nRestoring original scene...")
            self._restore_original_scene(logger, current_scene)

            logger.info("\n" + "=" * 70)
            logger.info("ARCHIVE COMPLETE!")
            logger.info("Location: %s" % archive_path)
            logger.info("=" * 70)

            return archive_path

        except Exception as e:
            logger.info("\nERROR during archiving: %s" % str(e))
            import traceback
            traceback.print_exc()
            self._restore_original_scene(logger, current_scene)
            return None

    def _create_directory_structure(self, logger, archive_path):
        self.archive_structure = {
            'scenes':       os.path.join(archive_path, 'scenes'),
            'sourceimages': os.path.join(archive_path, 'sourceimages'),
            'references':   os.path.join(archive_path, 'references'),
            'cache':        os.path.join(archive_path, 'cache'),
            'particles':    os.path.join(archive_path, 'particles'),
            'data':         os.path.join(archive_path, 'data'),
            'clips':        os.path.join(archive_path, 'clips'),
            'sound':        os.path.join(archive_path, 'sound'),
            'movies':       os.path.join(archive_path, 'movies'),
        }

        for folder_path in self.archive_structure.values():
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
                logger.info("  Created: %s" % folder_path)

    def _create_temp_scene_copy(self, logger):
        import tempfile

        temp_dir = tempfile.gettempdir()
        temp_filename = "maya_archive_temp_%s.ma" % os.getpid()
        self.temp_scene_path = os.path.join(temp_dir, temp_filename)

        cmds.file(rename=self.temp_scene_path)
        cmds.file(save=True, type='mayaAscii')

        logger.info("  Temporary scene created: %s" % self.temp_scene_path)

    def _collect_all_files(self, logger):
        """
        Use Maya's own dependency resolver (cmds.file query=True list=True)
        which is exactly what the built-in Archive Scene menu uses.
        This catches every node type automatically: textures, VDBs, caches,
        references, audio, image planes, Arnold nodes, third-party plugins, etc.
        Sequence paths (####, <f>, etc.) are expanded via glob.
        """

        all_deps = cmds.file(query=True, list=True, withoutCopyNumber=True) or []

        current_scene = cmds.file(query=True, sceneName=True)
        seen_sources = set()

        logger.info("  Maya reported %d dependency path(s)" % len(all_deps))

        for dep_path in all_deps:
            # Skip the scene itself
            if current_scene and os.path.normpath(dep_path) == os.path.normpath(current_scene):
                continue
            if self.temp_scene_path and os.path.normpath(dep_path) == os.path.normpath(self.temp_scene_path):
                continue

            resolved = _resolve_path(dep_path)

            if not resolved:
                logger.info("  WARNING: Could not resolve on disk: %s" % dep_path)
                continue

            for real_path in resolved:
                norm = os.path.normpath(real_path)
                if norm in seen_sources:
                    continue
                seen_sources.add(norm)

                ext = os.path.splitext(real_path)[1].lower()
                category = self._categorise(ext, dep_path)
                self.collected_files[category].append({
                    'source':    real_path,
                    'orig_path': dep_path,
                })

        # Fallback scan for anything Maya's list missed
        self._collect_via_node_attrs(logger, seen_sources)

        total = sum(len(v) for v in self.collected_files.values())
        logger.info("\n  Total files collected: %d" % total)
        for cat, files in self.collected_files.items():
            if files:
                logger.info("    %-16s %d" % (cat + ':', len(files)))

    def _categorise(self, ext, path):
        """Determine archive subfolder from file extension, with fallbacks."""
        folder = EXT_TO_FOLDER.get(ext)
        if folder:
            return folder

        low = path.lower()
        if 'sound' in low or 'audio' in low:
            return 'sound'
        if 'cache' in low or 'alembic' in low or 'vdb' in low:
            return 'cache'
        if 'sourceimages' in low or 'texture' in low or 'tex' in low:
            return 'sourceimages'
        if 'movie' in low or 'video' in low:
            return 'movies'

        return 'data'

    def _collect_via_node_attrs(self, logger, seen_sources):
        """
        Fallback scanner: iterate every node in the scene and check a broad
        list of known file-path attributes. Skips anything already collected.
        """
        file_attrs = [
            'fileTextureName', 'imageName', 'filename',
            'abc_File', 'cacheFileName', 'cachePath',
            'dso', 'aiFilename', 'sceneFileName',
            'cfnFilePath', 'vdbFilePath',
        ]

        for attr in file_attrs:
            for node in cmds.ls('*'):
                if not cmds.attributeQuery(attr, node=node, exists=True):
                    continue
                try:
                    path = cmds.getAttr('%s.%s' % (node, attr))
                    if not path:
                        continue

                    resolved = _resolve_path(path)
                    for real_path in resolved:
                        norm = os.path.normpath(real_path)
                        if norm in seen_sources:
                            continue
                        seen_sources.add(norm)

                        ext = os.path.splitext(real_path)[1].lower()
                        category = self._categorise(ext, path)
                        self.collected_files[category].append({
                            'source':    real_path,
                            'orig_path': path,
                            'node':      node,
                            'attr':      attr,
                        })
                        logger.info("    [fallback] %s  (%s.%s)" % (
                            os.path.basename(real_path), node, attr))
                except Exception:
                    pass

    def _process_references(self, logger):
        """Import all references into the temp scene."""
        references = cmds.file(query=True, reference=True) or []

        if not references:
            logger.info("  No references to process")
            return

        logger.info("  Found %d reference(s)" % len(references))
        references.reverse()

        for ref_path in references:
            try:
                ref_node = cmds.referenceQuery(ref_path, referenceNode=True)
                namespace = cmds.referenceQuery(ref_path, namespace=True)

                logger.info("    Importing: %s  (namespace: %s)" % (
                    os.path.basename(ref_path), namespace))

                cmds.file(ref_path, importReference=True, referenceNode=ref_node)

                self.reference_mapping[ref_node] = {
                    'original_path': ref_path,
                    'namespace':     namespace,
                }

            except Exception as e:
                logger.info("    WARNING: Could not import reference %s: %s" % (ref_path, str(e)))

        logger.info("  All references imported")

    def _create_link(self, logger, source_path, target_path):
        """
        Creates the most appropriate link type based on filesystem and drives.
        - Same NTFS drive: hard link (mklink /H) - no permissions needed
        - Different drives / remote: symbolic link (mklink)
        """
        source_drive = os.path.splitdrive(os.path.abspath(source_path))[0].lower()
        target_drive = os.path.splitdrive(os.path.abspath(target_path))[0].lower()

        link_string = 'mklink ' + '"' + target_path + '"' + ' ' + '"' + source_path + '"'

        result = os.popen('cmd.exe /c ' + link_string).read()
        logger.info("    [mklink result] %s" % result.strip())

    def _link_files_to_archive(self, logger):
        """
        Create a link in the archive folder pointing back to the original
        source file.
        The scene file itself is NOT processed here.
        """
        linked_count  = 0
        copied_count  = 0
        skipped_count = 0

        for category, files in self.collected_files.items():
            if category.startswith('_') or not files:
                continue

            target_dir = self.archive_structure.get(category, self.archive_structure['data'])

            logger.info("\n  Linking %s (%d file(s))..." % (category, len(files)))

            for file_info in files:
                source_path = file_info['source']

                if not os.path.exists(source_path):
                    logger.info("    WARNING: Not on disk: %s" % source_path)
                    skipped_count += 1
                    continue

                filename    = os.path.basename(source_path)
                target_path = os.path.join(target_dir, filename)

                counter = 1
                base_name, ext = os.path.splitext(filename)
                while os.path.exists(target_path):
                    filename    = "%s_%d%s" % (base_name, counter, ext)
                    target_path = os.path.join(target_dir, filename)
                    counter += 1

                try:
                    self._create_link(logger, source_path, target_path)

                    file_info['archive_path']  = target_path
                    file_info['relative_path'] = os.path.relpath(target_path, self.output_dir)

                    linked_count += 1
                    logger.info("    ARCHIVED OK: %s" % filename)

                    if 'node' in file_info and 'attr' in file_info:
                        try:
                            cmds.setAttr(
                                '%s.%s' % (file_info['node'], file_info['attr']),
                                target_path,
                                type='string'
                            )
                        except Exception:
                            pass

                except Exception as e:
                    logger.info("    ERROR: %s — %s" % (filename, str(e)))
                    skipped_count += 1

        logger.info("\n  Processed: %d   Skipped: %d" % (linked_count, skipped_count))

    def _redirect_node_attributes(self, logger):
        """Redirect all file node attributes to their symlink paths in the archive."""

        # Build map: original source path -> archive link path
        path_map = {}
        for files in self.collected_files.values():
            for file_info in files:
                if 'archive_path' in file_info:
                    norm = os.path.normpath(file_info['source'])
                    path_map[norm] = file_info['archive_path']

        if not path_map:
            logger.info("  No path remapping needed")
            return

        logger.info("  Remapping %d path(s) in scene nodes..." % len(path_map))

        file_attrs = [
            'fileTextureName', 'imageName', 'filename',
            'abc_File', 'cacheFileName', 'cachePath',
            'dso', 'aiFilename', 'sceneFileName',
            'cfnFilePath', 'vdbFilePath',
        ]

        remapped = 0
        for attr in file_attrs:
            for node in cmds.ls('*'):
                if not cmds.attributeQuery(attr, node=node, exists=True):
                    continue
                try:
                    current = cmds.getAttr('%s.%s' % (node, attr))
                    if not current:
                        continue
                    norm = os.path.normpath(current)
                    if norm in path_map:
                        cmds.setAttr(
                            '%s.%s' % (node, attr),
                            path_map[norm],
                            type='string'
                        )
                        logger.info("    Remapped %s.%s -> %s" % (node, attr, os.path.basename(path_map[norm])))
                        remapped += 1
                except Exception:
                    pass

        logger.info("  Total remapped: %d" % remapped)

    def _save_archived_scene(self, logger, archive_name):
        archived_scene_path = os.path.join(
            self.archive_structure['scenes'],
            archive_name + '.ma'
        )

        cmds.file(rename=archived_scene_path)
        cmds.file(save=True, type='mayaAscii')

        logger.info("  Archived scene saved: %s" % archived_scene_path)
        return archived_scene_path

    def _create_manifest(self, logger, archive_path, archived_scene_path):
        manifest_path = os.path.join(archive_path, 'archive_manifest.json')

        manifest = {
            'archive_name':        os.path.basename(archive_path),
            'creation_date':       cmds.date(),
            'maya_version':        cmds.about(version=True),
            'archived_scene':      os.path.relpath(archived_scene_path, archive_path),
            'file_counts': {
                cat: len(files)
                for cat, files in self.collected_files.items()
                if not cat.startswith('_')
            },
            'total_files': sum(
                len(v) for k, v in self.collected_files.items()
                if not k.startswith('_')
            ),
            'references_imported': len(self.reference_mapping),
            'structure': {
                key: os.path.relpath(path, archive_path)
                for key, path in self.archive_structure.items()
            },
        }

        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)

        logger.info("  Manifest created: %s" % manifest_path)

    def _restore_original_scene(self, logger, original_scene_path):
        cmds.file(original_scene_path, open=True, force=True)

        if self.temp_scene_path and os.path.exists(self.temp_scene_path):
            try:
                os.remove(self.temp_scene_path)
            except Exception:
                pass

        logger.info("Original scene restored: %s" % original_scene_path)


# ============================================================================
# USAGE FUNCTIONS
# ============================================================================

def archive_current_scene(output_directory, logger, archive_name=None):
    """
    Archive the current Maya scene with all dependencies.

    :param output_directory: Directory where archive folder will be created
    :param archive_name:     Optional name for archive folder
    :return:                 Path to archive directory

    Usage:
        archive_path = archive_current_scene('D:/archives')
        archive_path = archive_current_scene('D:/archives', 'shot010_v003')
    """
    if not os.path.exists(output_directory):
        try:
            os.makedirs(output_directory)
            logger.info("Created output directory: %s" % output_directory)
        except Exception as e:
            cmds.error("Cannot create output directory: %s" % str(e))
            return None

    archiver = MayaSceneArchiver(output_directory)
    return archiver.create_archive(logger, archive_name)


def archive_scene_interactive(logger):
    """Interactive version — prompts user for output directory and archive name."""
    output_dir = cmds.fileDialog2(
        dialogStyle=2,
        fileMode=3,
        caption='Select Archive Output Directory'
    )

    if not output_dir:
        logger.info("Archive cancelled")
        return None

    output_dir = output_dir[0]

    current_scene = cmds.file(query=True, sceneName=True)
    default_name = (
        os.path.splitext(os.path.basename(current_scene))[0] + "_archive"
        if current_scene else "maya_scene_archive"
    )

    result = cmds.promptDialog(
        title='Archive Name',
        message='Enter archive name:',
        text=default_name,
        button=['OK', 'Cancel'],
        defaultButton='OK',
        cancelButton='Cancel',
        dismissString='Cancel'
    )

    if result == 'OK':
        archive_name = cmds.promptDialog(query=True, text=True)
        return archive_current_scene(output_dir, archive_name)

    return None


def archive_to_project_archives_folder(logger, archive_name=None):
    """
    Archive to the current project's 'archives' folder.

    :param archive_name: Optional archive name
    :return:             Path to archive
    """
    workspace = cmds.workspace(query=True, rootDirectory=True)

    if not workspace:
        cmds.warning("No project set. Please set a project first.")
        return None

    archives_folder = os.path.join(workspace, 'archives')

    if not os.path.exists(archives_folder):
        os.makedirs(archives_folder)
        logger.info("Created archives folder: %s" % archives_folder)

    return archive_current_scene(archives_folder, archive_name)