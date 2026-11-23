# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import hashlib
import os
import traceback
import re
import nuke
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

# A look up of node types to parameters for finding outputs to publish
_NUKE_OUTPUTS = {
    "Write": "file",
    "WriteGeo": "file",
}

# (work template, publish template) pairs used to recognise the PRECOMP renders
# that the Read nodes of a script point at (shot and asset steps)
_PRECOMP_TEMPLATES = [
    ("nuke_precomp", "nuke_precomp_pub"),
    ("nuke_asset_precomp", "nuke_asset_precomp_pub"),
]

# Profiles of the write nodes whose renders are also collected from the Read
# nodes that point at them (the templates come from the tk-nuke-writenode
# profiles): profile -> (divider key, (divider item type, name, display name),
# publish type, is it a movie)
_READ_PROFILES = {
    "PRECOMP": ("PRECOMP", ("nuke.session.precomp", "PRECOMPS", "All Session PRECOMPS"), "PRECOMP", False),
    "MATTE_PAINT": ("MATTE_PAINT", ("nuke.session.mattepaint", "MATTE_PAINTS", "All Session MATTE_PAINTS"), "BG_MATTEPAINT", False),
    "IMAGE_PLANE": ("IMAGE_PLANE", ("nuke.session.imageplane", "IMAGE_PLANES", "All Session IMAGE_PLANES"), "IMAGE_PLANE", False),
    "IMAGE_PLANE_MOV": ("IMAGE_PLANE", ("nuke.session.imageplane", "IMAGE_PLANES", "All Session IMAGE_PLANES"), "IMAGE_PLANE", True),
    "ALPHA": ("ALPHA", ("nuke.session.alpha", "ALPHAS", "All Session ALPHAS"), "ALPHA_RENDER", False),
    # h264 movie of a precomp: same as PRECOMP but a single .mp4 file
    "PRECOMP_MP4": ("PRECOMP", ("nuke.session.precomp", "PRECOMPS", "All Session PRECOMPS"), "PRECOMP", True),
}
# Write node profiles whose items are checked by default only when they are used
# in the tree of the Render write nodes
_TREE_PROFILES = ("PRECOMP", "PRECOMP_MP4", "TECH_PRECOMP", "MATTE_PAINT", "IMAGE_PLANE", "IMAGE_PLANE_MOV", "ALPHA")

# PRECOMP and TECH_PRECOMP share templates: a PRECOMP render whose EXR channels
# are all 32 bit float is a TECH_PRECOMP
_TECH_PRECOMP_PROFILE = (
    "TECH_PRECOMP",
    ("nuke.session.tech_precomp", "TECH_PRECOMPS", "All Session TECH_PRECOMPS"),
    "TECH_PRECOMP",
    False,
)

# External dependencies: the render write nodes (profile names) whose tree is
# analysed, the folders of the pipeline that are never touched and the place
# where the identity of the material is stored
_EXTERNAL_ROOT_PROFILES = ("Render 16bits", "Render JPG")
_PIPELINE_FOLDERS = ("publish", "source", "vref")
_FINGERPRINT_FIELD = "sg_source_fingerprint"
_FINGERPRINT_SIDECAR = "_fingerprint.txt"

# shown in the publisher log to check which version of this hook is loaded
_BUILD = "externals v13 mp4-range (2026-11-23 15:30)"


class NukeSessionCollector(HookBaseClass):
    """
    Collector that operates on the current nuke/nukestudio session. Should
    inherit from the basic collector hook.
    """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.

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

        # grab any base class settings
        collector_settings = super(NukeSessionCollector, self).settings or {}

        # settings specific to this collector
        nuke_session_settings = {
            "Work Template": {
                "type": "template",
                "default": None,
                "description": "Template path for artist work files. Should "
                "correspond to a template defined in "
                "templates.yml. If configured, is made available"
                "to publish plugins via the collected item's "
                "properties. ",
            },
        }

        # update the base settings with these settings
        collector_settings.update(nuke_session_settings)

        return collector_settings

    def process_current_session(self, settings, parent_item):
        """
        Analyzes the current session open in Nuke/NukeStudio and parents a
        subtree of items under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        """

        publisher = self.parent
        engine = publisher.engine

        self.logger.info("=== NUKE COLLECTOR build %s (%s) ===" % (_BUILD, os.path.abspath(__file__)))

        if nuke.root().knob("proxy").value()==False:
            if (hasattr(engine, "studio_enabled") and engine.studio_enabled) or (
                hasattr(engine, "hiero_enabled") and engine.hiero_enabled
            ):

                # running nuke studio or hiero
                self.collect_current_nukestudio_session(settings, parent_item)

                # since we're in NS, any additional collected outputs will be
                # parented under the root item
                project_item = parent_item
            else:
                # running nuke. ensure additional collected outputs are parented
                # under the session
                project_item = self.collect_current_nuke_session(settings, parent_item)

            # run node collection if not in hiero
            if hasattr(engine, "hiero_enabled") and not engine.hiero_enabled:
                item_types = {}
                self._write_dirs = set()
                self.collect_sg_writenodes(project_item, item_types)
                self.collect_precomp_reads(project_item, item_types)
                try:
                    self.collect_external_dependencies(project_item, item_types)
                except Exception:
                    self.logger.error(
                        "External dependencies failed:\n%s" % (traceback.format_exc(),)
                    )
                self.collect_sg_writeGeoCam_nodes(project_item, item_types)
                self.collect_sg_writeGeo_nodes(project_item, item_types)
                self.collect_node_outputs(project_item)
                # the Renders divider goes last, so the Render items are
                # published after everything else
                self._move_item_last(project_item, item_types.get("RENDER"))
        else:
            nuke.message("Estás en modo proxy. Desactivalo para publicar")

    def _move_item_last(self, parent_item, child):
        """
        Move child to the end of the children of parent_item. The publisher
        runs (and shows) the items in the order of the children.
        """
        try:
            if child is not None and child in parent_item._children:
                parent_item._children.remove(child)
                parent_item._children.append(child)
                self.logger.info("[%s] '%s' moved to the end of the publish order" % (_BUILD, child.name))
        except Exception as e:
            self.logger.warning("[%s] Could not reorder the items: %s" % (_BUILD, e))

    def collect_current_nuke_session(self, settings, parent_item):
        """
        Analyzes the current session open in Nuke and parents a subtree of items
        under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        """

        publisher = self.parent

        # get the current path
        path = _session_path()

        # determine the display name for the item
        if path:
            file_info = publisher.util.get_file_path_components(path)
            display_name = file_info["filename"]
        else:
            display_name = "Current Nuke Session"

        # create the session item for the publish hierarchy
        session_item = parent_item.create_item(
            "nuke.session", "Nuke Script", display_name
        )

        # get the icon path to display for this item
        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "nuke.png")
        session_item.set_icon_from_path(icon_path)

        # if a work template is defined, add it to the item properties so
        # that it can be used by attached publish plugins
        work_template_setting = settings.get("Work Template")
        if work_template_setting:
            work_template = publisher.engine.get_template_by_name(
                work_template_setting.value
            )

            # store the template on the item for use by publish plugins. we
            # can't evaluate the fields here because there's no guarantee the
            # current session path won't change once the item has been created.
            # the attached publish plugins will need to resolve the fields at
            # execution time.
            session_item.properties["work_template"] = work_template
            self.logger.debug("Work template defined for Nuke collection.")

        self.logger.info("Collected current Nuke script")
        return session_item

    def collect_current_nukestudio_session(self, settings, parent_item):
        """
        Analyzes the current session open in NukeStudio and parents a subtree of
        items under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        """

        # import here since the hooks are imported into nuke and nukestudio.
        # hiero module is only available in later versions of nuke
        import hiero.core

        publisher = self.parent


        # go ahead and build the path to the icon for use by any projects
        icon_path = os.path.join(
            self.disk_location, os.pardir, "icons", "nukestudio.png"
        )

        if hiero.ui.activeSequence():
            active_project = hiero.ui.activeSequence().project()
        else:
            active_project = None

        # attempt to retrive a configured work template. we can attach
        # it to the collected project items
        work_template_setting = settings.get("Work Template")
        work_template = None
        if work_template_setting:
            work_template = publisher.engine.get_template_by_name(
                work_template_setting.value
            )

        # FIXME: begin temporary workaround
        # we use different logic here only because we don't have proper support
        # for multi context workflows when templates are in play. So if we have
        # a work template configured, for now we'll only collect the current,
        # active document. Once we have proper multi context support, we can
        # remove this.
        if work_template:
            # same logic as the loop below but only processing the active doc
            if not active_project:
                return
            project_item = parent_item.create_item(
                "nukestudio.project", "NukeStudio Project", active_project.name()
            )
            self.logger.info(
                "Collected Nuke Studio project: %s" % (active_project.name(),)
            )
            project_item.set_icon_from_path(icon_path)
            project_item.properties["project"] = active_project
            project_item.properties["work_template"] = work_template
            self.logger.debug("Work template defined for NukeStudio collection.")
            return
        # FIXME: end temporary workaround

        for project in hiero.core.projects():

            # create the session item for the publish hierarchy
            project_item = parent_item.create_item(
                "nukestudio.project", "NukeStudio Project", project.name()
            )
            project_item.set_icon_from_path(icon_path)

            # add the project object to the properties so that the publish
            # plugins know which open project to associate with this item
            project_item.properties["project"] = project

            self.logger.info("Collected Nuke Studio project: %s" % (project.name(),))

            # enable the active project and expand it. other projects are
            # collapsed and disabled.
            if active_project and active_project.guid() == project.guid():
                project_item.expanded = True
                project_item.checked = True
            elif active_project:
                # there is an active project, but this isn't it. collapse and
                # disable this item
                project_item.expanded = False
                project_item.checked = False

            # store the template on the item for use by publish plugins. we
            # can't evaluate the fields here because there's no guarantee the
            # current session path won't change once the item has been created.
            # the attached publish plugins will need to resolve the fields at
            # execution time.
            if work_template:
                project_item.properties["work_template"] = work_template
                self.logger.debug("Work template defined for NukeStudio collection.")

    def collect_node_outputs(self, parent_item):
        """
        Scan known output node types in the session and see if they reference
        files that have been written to disk.

        :param parent_item: The parent item for any nodes collected
        """
        # iterate over all the known output types
        for node_type in _NUKE_OUTPUTS:
            ##Limit this routine for WriteGeo nodes until we have a workflow
            if node_type == 'WriteGeo':

                # get all the instances of the node type
                all_nodes_of_type = [n for n in nuke.allNodes() if n.Class() == node_type]

                # iterate over each instance
                for node in all_nodes_of_type:

                    param_name = _NUKE_OUTPUTS[node_type]

                    # evaluate the output path parameter which may include frame
                    # expressions/format
                    file_path = node[param_name].evaluate()

                    if not file_path or not os.path.exists(file_path):
                        # no file or file does not exist, nothing to do
                        continue

                    self.logger.info("Processing %s node: %s" % (node_type, node.name()))

                    # file exists, let the basic collector handle it
                    item = super(NukeSessionCollector, self)._collect_file(
                        parent_item, file_path, frame_sequence=True
                    )

                    # the item has been created. update the display name to include
                    # the nuke node to make it clear to the user how it was
                    # collected within the current session.
                    item.name = "%s (%s)" % (item.name, node.name())

    def collect_sg_writenodes(self, parent_item, item_types):
        """
        Collect any rendered sg write nodes in the session.

        :param parent_item:  The parent item for any sg write nodes collected
        """

        publisher = self.parent
        engine = publisher.engine

        sg_writenode_app = engine.apps.get("tk-nuke-writenode")
        if not sg_writenode_app:
            self.logger.debug(
                "The tk-nuke-writenode app is not installed. "
                "Will not attempt to collect those nodes."
            )
            return

        first_frame = int(nuke.root()["first_frame"].value())
        last_frame = int(nuke.root()["last_frame"].value())

        # folders of the renders that the Render write nodes use through a Read
        tree_folders = self._tree_read_folders()

        for node in sg_writenode_app.get_write_nodes():
            # publish_path_CHECK = sg_writenode_app.get_node_render_path(node)


            # see if any frames have been rendered for this write node
            rendered_files = sg_writenode_app.get_node_render_files(node)
            try:
                rendered_files = sorted(rendered_files)
            except:
                self.logger.info ("Unable to sort the rendered files")
            if not rendered_files:
                continue

            # some files rendered, use first frame to get some publish item info
            path = rendered_files[0]
            item_info = super(NukeSessionCollector, self)._get_item_info(path)

            # item_info will be for the single file. we'll update the type and
            # display to represent a sequence. This is the same pattern used by
            # the base collector for image sequences. We're not using the base
            # collector to create the publish item though since we already have
            # the sequence path, template knowledge provided by the
            # tk-nuke-writenode app. The base collector makes some "zero config"
            # assupmtions about the path that we don't need to make here.
            if node.knob('tk_profile_list').value() in ["IMAGE_PLANE_MOV", "PRECOMP_MP4"]:
                item_type = "%s.video" % (item_info["item_type"],)
                type_display = "%s Video" % (item_info["type_display"],)
            else:
                item_type = "%s.sequence" % (item_info["item_type"],)
                type_display = "%s Sequence" % (item_info["type_display"],)
            # we'll publish the path with the frame/eye spec (%V, %04d)
            publish_path = sg_writenode_app.get_node_render_path(node)

            # construct publish name:
            render_template = sg_writenode_app.get_node_render_template(node)
            render_path_fields = render_template.get_fields(publish_path)


            publish_name = "%s %s" % ('_'.join(os.path.splitext(os.path.basename(publish_path))[0].split('_')[:-1]), node.knob('tank_channel').value())

            # get the version number from the render path
            version_number = render_path_fields.get("version")

            # use the path basename and nuke writenode name for display
            (_, filename) = os.path.split(publish_path)
            display_name = "%s (%s)" % (publish_name, node.name())
            icon_path = item_info["icon_path"]


            if node.knob('tk_profile_list').value() == "MATTE_PAINT":
                if "MATTE_PAINT" not in item_types:
                    renderdivider = parent_item.create_item("nuke.session.mattepaint", "MATTE_PAINTS",
                                                            "All Session MATTE_PAINTS")
                    renderdivider.set_icon_from_path(icon_path)
                    renderdivider.expanded = False
                    item_types["MATTE_PAINT"] = renderdivider
                # create and populate the item
                item = item_types["MATTE_PAINT"].create_item(item_type, type_display, display_name)
                item.set_icon_from_path(item_info["icon_path"])
                item.properties["publish_type"] = "BG_MATTEPAINT"

            elif node.knob('tk_profile_list').value() in ["IMAGE_PLANE", "IMAGE_PLANE_MOV"]:
                if "IMAGE_PLANE" not in item_types:
                    renderdivider = parent_item.create_item("nuke.session.imageplane", "IMAGE_PLANES",
                                                            "All Session IMAGE_PLANES")
                    renderdivider.set_icon_from_path(icon_path)
                    renderdivider.expanded = False
                    item_types["IMAGE_PLANE"] = renderdivider
                # create and populate the item
                item = item_types["IMAGE_PLANE"].create_item(item_type, type_display, display_name)
                item.set_icon_from_path(item_info["icon_path"])
                item.properties["publish_type"] = "IMAGE_PLANE"

            elif node.knob('tk_profile_list').value() in ["PRECOMP", "PRECOMP_MP4"]:
                if "PRECOMP" not in item_types:
                    renderdivider = parent_item.create_item("nuke.session.precomp", "PRECOMPS",
                                                            "All Session PRECOMPS")
                    renderdivider.set_icon_from_path(icon_path)
                    renderdivider.expanded = False
                    item_types["PRECOMP"] = renderdivider
                # create and populate the item
                item = item_types["PRECOMP"].create_item(item_type, type_display, display_name)
                item.set_icon_from_path(item_info["icon_path"])
                item.properties["publish_type"] = "PRECOMP"
                if node.knob('tk_profile_list').value() == "PRECOMP_MP4":
                    # a single movie: start frame of the write (or of the script), number of
                    # frames read from the movie itself
                    mp4_start = first_frame
                    try:
                        if node.knob("use_limit") and node["use_limit"].value():
                            mp4_start = int(node["first"].value())
                    except Exception:
                        pass
                    mp4_count = None
                    try:
                        mp4_count = _mp4_frame_count(rendered_files[0])
                    except Exception as e:
                        self.logger.debug("Could not read the frame count of %s: %s" % (rendered_files[0], e))
                    if mp4_count:
                        item.properties["render_first"] = mp4_start
                        item.properties["render_last"] = mp4_start + mp4_count - 1
                    else:
                        item.properties["render_first"] = first_frame
                        item.properties["render_last"] = last_frame
                else:
                    item.properties["render_first"] = int(rendered_files[0][-8:-4])
                    item.properties["render_last"] = int(rendered_files[-1][-8:-4])

            elif node.knob('tk_profile_list').value() == "TECH_PRECOMP":
                if "TECH_PRECOMP" not in item_types:
                    renderdivider = parent_item.create_item("nuke.session.tech_precomp", "TECH_PRECOMPS",
                                                            "All Session TECH_PRECOMPS")
                    renderdivider.set_icon_from_path(icon_path)
                    renderdivider.expanded = False
                    item_types["TECH_PRECOMP"] = renderdivider
                # create and populate the item
                item = item_types["TECH_PRECOMP"].create_item(item_type, type_display, display_name)
                item.set_icon_from_path(item_info["icon_path"])
                item.properties["publish_type"] = "TECH_PRECOMP"
                item.properties["render_first"] = int(rendered_files[0][-8:-4])
                item.properties["render_last"] = int(rendered_files[-1][-8:-4])

            elif node.knob('tk_profile_list').value() == "ALPHA":
                if "ALPHA" not in item_types:
                    renderdivider = parent_item.create_item("nuke.session.alpha", "ALPHAS",
                                                            "All Session ALPHAS")
                    renderdivider.set_icon_from_path(icon_path)
                    renderdivider.expanded = False
                    item_types["ALPHA"] = renderdivider
                # create and populate the item
                item = item_types["ALPHA"].create_item(item_type, type_display, display_name)
                item.set_icon_from_path(item_info["icon_path"])
                item.properties["publish_type"] = "ALPHA_RENDER"

            else:
                if "RENDER" not in item_types:
                    renderdivider = parent_item.create_item("nuke.session.renders", "RENDERS",
                                                            "All Session Renders")
                    renderdivider.set_icon_from_path(icon_path)
                    renderdivider.expanded = False
                    item_types["RENDER"] = renderdivider
                # create and populate the item
                item = item_types["RENDER"].create_item(item_type, type_display, display_name)
                item.set_icon_from_path(item_info["icon_path"])
                item.properties["publish_type"] = "RENDER_NUKE"

            # if the supplied path is an image, use the path as # the thumbnail.
            item.set_thumbnail_from_path(path)

            # disable thumbnail creation since we get it for free
            item.thumbnail_enabled = False

            # all we know about the file is its path. set the path in its
            # properties for the plugins to use for processing.
            item.properties["path"] = publish_path
            render_folder = os.path.normcase(os.path.dirname(os.path.normpath(publish_path)))
            if not hasattr(self, "_write_dirs"):
                self._write_dirs = set()
            self._write_dirs.add(render_folder)

            # the renders of these profiles are published by default only when
            # a Read of the Render trees uses them
            if node.knob('tk_profile_list').value() in _TREE_PROFILES:
                reads_using_it = tree_folders.get(render_folder)
                item.properties["in_tree"] = bool(reads_using_it)
                if reads_using_it:
                    # the Read nodes to repoint to the publish path once published
                    item.properties["read_nodes"] = list(reads_using_it)

            # include an indicator that this is an image sequence and the known
            # file that belongs to this sequence
            item.properties["sequence_paths"] = rendered_files

            # store publish info on the item so that the base publish plugin
            # doesn't fall back to zero config path parsing
            item.properties["publish_name"] = publish_name
            item.properties["publish_version"] = version_number
            item.properties[
                "publish_template"
            ] = sg_writenode_app.get_node_publish_template(node)
            item.properties[
                "work_template"
            ] = sg_writenode_app.get_node_render_template(node)
            item.properties["color_space"] = self._get_node_colorspace(node)
            item.properties["first_frame"] = first_frame
            item.properties["last_frame"] = last_frame
            if node.knob('tk_profile_list').value() == "PRECOMP_MP4" and item.properties.get("render_first") is not None:
                # frame range of what was rendered, not of the script
                item.properties["first_frame"] = item.properties["render_first"]
                item.properties["last_frame"] = item.properties["render_last"]

            # store the nuke writenode on the item as well. this can be used by
            # secondary publish plugins
            item.properties["sg_writenode"] = node


            # Collect dependencies from node
            item.properties["publish_dependencies"] = self.list_dependencies(node)

            # we have a publish template so disable context change. This
            # is a temporary measure until the publisher handles context
            # switching natively.
            item.context_change_allowed = False

            self.logger.info("Collected file: %s" % (publish_path,))


    def _tree_read_folders(self):
        """
        The Read nodes (enabled) that contribute to the Render write nodes,
        grouped by the folder of their file.

        :returns: Dictionary {normalised folder: [full names of the Read nodes]}
        """
        folders = {}
        for node in self._precomp_read_nodes():
            try:
                if node["disable"].value():
                    continue
                path = _read_file_path(node)
            except Exception:
                continue
            if not path:
                continue
            folder = os.path.normcase(os.path.dirname(os.path.normpath(path)))
            folders.setdefault(folder, []).append(node.fullName())
        return folders

    def _read_profile_templates(self):
        """
        Work and publish templates of the write node profiles listed in
        ``_READ_PROFILES``, read from the tk-nuke-writenode settings.

        :returns: List of dictionaries {profile, work, publish}
        """
        tk = self.parent.sgtk
        app = self.parent.engine.apps.get("tk-nuke-writenode")
        profiles = None
        try:
            profiles = app.get_setting("write_nodes") if app else None
        except Exception as e:
            self.logger.debug("Could not read the write node profiles: %s" % (e,))

        def template(value):
            if not value:
                return None
            return value if hasattr(value, "validate") else tk.templates.get(value)

        result = []
        for profile in profiles or []:
            name = profile.get("name")
            if name not in _READ_PROFILES:
                continue
            work = template(profile.get("render_template"))
            publish = template(profile.get("publish_template"))
            if work and publish:
                result.append({"profile": name, "work": work, "publish": publish})

        if not any(r["profile"] == "PRECOMP" for r in result):
            # no profile settings available: the fixed PRECOMP templates
            for work_name, publish_name in _PRECOMP_TEMPLATES:
                work = tk.templates.get(work_name)
                publish = tk.templates.get(publish_name)
                if work and publish:
                    result.append({"profile": "PRECOMP", "work": work, "publish": publish})
        return result

    def collect_precomp_reads(self, parent_item, item_types):
        """
        Collect the renders of the PRECOMP, MATTE_PAINT, IMAGE_PLANE and ALPHA
        profiles used by the Read nodes of the session that have not been
        published to Flow yet.

        A Read is treated as one of them when its file matches the work
        template of the profile and belongs to the entity of the current
        context. Reads that point somewhere else (plates, files that are
        already in the PUBLISH area, other shots...) are ignored, and so are
        the ones whose render is already registered in Flow or that are
        collected from their own write node.

        :param parent_item: The parent item for any items collected
        :param item_types:  Dictionary of divider items already created
        """

        publisher = self.parent
        tk = publisher.sgtk

        profiles = self._read_profile_templates()
        if not profiles:
            return

        context = parent_item.context
        entity = context.entity if context else None
        tech_precomp_dirs = self._get_tech_precomp_dirs()
        write_dirs = getattr(self, "_write_dirs", set())

        # ---- group the Read nodes by the render they point at
        candidates = {}
        for node in self._precomp_read_nodes():
            try:
                if node["disable"].value():
                    continue
                read_path = _read_file_path(node)
            except Exception as e:
                self.logger.debug("Could not evaluate Read '%s': %s" % (node.name(), e))
                continue
            if not read_path:
                continue
            read_path = os.path.normpath(read_path)

            match = None
            for profile in profiles:
                if profile["work"].validate(read_path):
                    match = profile
                    break
            if match is None:
                # not a render of the work area of any of the profiles
                continue
            fields = match["work"].get_fields(read_path)

            if entity and fields.get(entity["type"]) not in (None, entity.get("name")):
                self.logger.debug(
                    "Read '%s' belongs to another entity, skipping: %s"
                    % (node.name(), read_path)
                )
                continue

            folder = os.path.normcase(os.path.dirname(read_path))
            if folder in tech_precomp_dirs:
                # handled by the TECH_PRECOMP write node
                continue
            if folder in write_dirs:
                # handled by its write node
                self.logger.debug(
                    "Read '%s' points at a render collected from its write node, skipping: %s"
                    % (node.name(), read_path)
                )
                continue

            key = os.path.normcase(read_path)
            if key in candidates:
                candidates[key]["nodes"].append(node)
            else:
                candidates[key] = {
                    "path": read_path,
                    "fields": fields,
                    "profile": match["profile"],
                    "work_template": match["work"],
                    "publish_template": match["publish"],
                    "nodes": [node],
                }

        # ---- keep the ones that exist on disk
        try:
            script_first = int(nuke.root()["first_frame"].value())
            script_last = int(nuke.root()["last_frame"].value())
        except Exception:
            script_first, script_last = 1, 1

        ready = []
        for candidate in candidates.values():
            is_movie = _READ_PROFILES[candidate["profile"]][3]
            if is_movie:
                frames = (
                    [(script_first, candidate["path"])]
                    if os.path.isfile(candidate["path"]) else []
                )
            else:
                frames = self._find_sequence_files(candidate["path"])
            if not frames:
                folder = os.path.dirname(candidate["path"])
                try:
                    listing = sorted(os.listdir(folder))
                except OSError:
                    listing = None
                self.logger.warning(
                    "[%s]" % _BUILD + " Read '%s' has no frames on disk, skipping. "
                    "path: %s | folder exists: %s | files in folder: %s | sample: %s"
                    % (
                        candidate["nodes"][0].name(), candidate["path"],
                        listing is not None, len(listing or []), (listing or [])[:3],
                    )
                )
                continue
            publish_template = candidate["publish_template"]
            if publish_template.missing_keys(candidate["fields"]):
                self.logger.warning(
                    "Could not build the publish path for: %s" % (candidate["path"],)
                )
                continue
            candidate["frames"] = frames
            candidate["publish_path"] = publish_template.apply_fields(
                candidate["fields"]
            )
            ready.append(candidate)
        if not ready:
            return

        # ---- drop the ones that are already published in Flow
        published = set()
        try:
            found = sgtk.util.find_publish(
                tk, [candidate["publish_path"] for candidate in ready]
            )
            published = set(os.path.normcase(os.path.normpath(p)) for p in found)
        except Exception as e:
            # publish validation still blocks duplicates, so listing is safe
            self.logger.warning(
                "Could not check which renders are already published: %s" % (e,)
            )

        for candidate in sorted(ready, key=lambda c: c["publish_path"]):
            publish_path = candidate["publish_path"]
            if os.path.normcase(os.path.normpath(publish_path)) in published:
                self.logger.debug("%s already published: %s" % (candidate["profile"], publish_path))
                continue

            divider_key, divider_def, publish_type, is_movie = _READ_PROFILES[candidate["profile"]]
            fields = candidate["fields"]
            frames = candidate["frames"]
            nodes = candidate["nodes"]
            first_path = frames[0][1]
            profile_name = candidate["profile"]
            if profile_name == "PRECOMP" and _exr_is_32bit_float(first_path):
                divider_key, divider_def, publish_type, is_movie = _TECH_PRECOMP_PROFILE
                profile_name = "TECH_PRECOMP"
                self.logger.debug("32 bit float EXR, published as TECH_PRECOMP: %s" % (first_path,))
            if is_movie:
                first_frame, last_frame = script_first, script_last
                if profile_name == "PRECOMP_MP4":
                    # start frame of the Read ("start at") and number of frames of the movie
                    try:
                        mp4_start = script_first
                        rn = nodes[0]
                        if rn.knob("frame_mode") and rn["frame_mode"].value() == "start at":
                            mp4_start = int(float(rn["frame"].value()))
                        mp4_count = _mp4_frame_count(first_path)
                        if mp4_count:
                            first_frame, last_frame = mp4_start, mp4_start + mp4_count - 1
                    except Exception as e:
                        self.logger.debug("Could not read the frame range of %s: %s" % (first_path, e))
            else:
                first_frame, last_frame = frames[0][0], frames[-1][0]

            item_info = super(NukeSessionCollector, self)._get_item_info(first_path)
            if is_movie:
                item_type = "%s.video" % (item_info["item_type"],)
                type_display = "%s Video" % (item_info["type_display"],)
            else:
                item_type = "%s.sequence" % (item_info["item_type"],)
                type_display = "%s Sequence" % (item_info["type_display"],)

            # same naming as the one used for the write nodes:
            # "<name without version> <output>"
            publish_name = "_".join(
                os.path.splitext(os.path.basename(publish_path))[0].split("_")[:-1]
            )
            output = fields.get("nuke.output") or fields.get("output")
            if output:
                publish_name = "%s %s" % (publish_name, output)
            display_name = "%s (%s)" % (
                publish_name,
                ", ".join(sorted(n.name() for n in nodes)),
            )

            if divider_key not in item_types:
                divider = parent_item.create_item(*divider_def)
                divider.set_icon_from_path(item_info["icon_path"])
                divider.expanded = False
                item_types[divider_key] = divider

            item = item_types[divider_key].create_item(
                item_type, type_display, display_name
            )
            item.set_icon_from_path(item_info["icon_path"])
            item.set_thumbnail_from_path(first_path)
            item.thumbnail_enabled = False

            item.properties["publish_type"] = publish_type
            item.properties["in_tree"] = True
            item.properties["path"] = candidate["path"]
            item.properties["sequence_paths"] = [f[1] for f in frames]
            item.properties["publish_name"] = publish_name
            item.properties["publish_version"] = fields.get("version")
            item.properties["publish_template"] = candidate["publish_template"]
            item.properties["work_template"] = candidate["work_template"]
            item.properties["color_space"] = self._get_node_colorspace(nodes[0])
            item.properties["first_frame"] = first_frame
            item.properties["last_frame"] = last_frame
            item.properties["render_first"] = first_frame
            item.properties["render_last"] = last_frame
            item.properties["publish_dependencies"] = []

            # the Read nodes to repoint to the publish path once published
            item.properties["read_nodes"] = [n.fullName() for n in nodes]

            item.context_change_allowed = False

            self.logger.info(
                "Collected %s from Read: %s" % (profile_name, candidate["path"])
            )

    def _precomp_read_nodes(self):
        """
        The Read nodes that contribute to the Render write nodes (groups are
        entered, LiveGroups are not). When there is no Render write node, all
        the Reads of the script are considered.
        """
        app = self.parent.engine.apps.get("tk-nuke-writenode")
        roots = []
        if app:
            for node in app.get_write_nodes():
                try:
                    if node.knob("tk_profile_list").value() in _EXTERNAL_ROOT_PROFILES:
                        roots.append(node)
                except Exception:
                    continue
        if not roots:
            self.logger.info(
                "PRECOMP from Reads: no Render write nodes, using every Read of the script."
            )
            return nuke.allNodes("Read", recurseGroups=True)
        return [n for n in self._walk_render_trees(roots) if n.Class() == "Read"]

    def _get_tech_precomp_dirs(self):
        """
        Folders of the TECH_PRECOMP write nodes. They share the PRECOMP
        templates but are still collected from their write nodes.
        """
        dirs = set()
        app = self.parent.engine.apps.get("tk-nuke-writenode")
        if not app:
            return dirs
        for node in app.get_write_nodes():
            try:
                if node.knob("tk_profile_list").value() != "TECH_PRECOMP":
                    continue
                render_path = os.path.normpath(app.get_node_render_path(node))
                dirs.add(os.path.normcase(os.path.dirname(render_path)))
            except Exception:
                continue
        return dirs

    def _find_sequence_files(self, path):
        """
        List the frames on disk of an image sequence path (``name.%04d.exr``).

        :param path: Sequence path with a frame spec
        :returns: Sorted list of (frame number, file path) tuples
        """
        folder, pattern = os.path.split(path)
        spec = re.search(r"%\d*d", pattern)
        if not spec:
            return []
        regex = re.compile(
            "^%s(\\d+)%s$"
            % (re.escape(pattern[: spec.start()]), re.escape(pattern[spec.end():])),
            re.IGNORECASE if os.name == "nt" else 0,
        )
        try:
            names = os.listdir(folder)
        except OSError:
            return []
        frames = []
        for name in names:
            match = regex.match(name)
            if match:
                frames.append((int(match.group(1)), os.path.join(folder, name)))
        frames.sort()
        return frames

    def collect_external_dependencies(self, parent_item, item_types):
        """
        Collect the material that the Render write nodes need and that lives
        outside the pipeline: image sequences/files (Read), cameras and axes
        read from file, and ReadGeo nodes. Everything that contributes to a
        ``_EXTERNAL_ROOT_PROFILES`` write node is analysed (groups are entered,
        LiveGroups are not).

        - Image sequences and files outside the pipeline go to
          ``VFX/ASSETS/EXTERNAL/<name>/v###`` (identified by a content
          fingerprint, so the same material is never published twice).
        - Cameras and geo use the camera/geo publish templates of the entity,
          with the version of the open script.
        - Files inside the STEPS folder of the current step are moved, any other
          is copied.
        - SOURCE, VREF and PUBLISH files are never touched.

        Nothing is changed here. The items hold the plan that
        ``publish_file.py`` executes before the script is saved.

        :param parent_item: The parent item for any items collected
        :param item_types:  Dictionary of divider items already created
        """

        publisher = self.parent
        tk = publisher.sgtk
        engine = publisher.engine

        self.logger.info("External dependencies: starting")
        app = engine.apps.get("tk-nuke-writenode")
        if not app:
            self.logger.info("External dependencies: tk-nuke-writenode is not available")
            return

        roots = []
        profiles_found = []
        for node in app.get_write_nodes():
            try:
                profile = node.knob("tk_profile_list").value()
                profiles_found.append("%s (%s)" % (node.name(), profile))
                if profile in _EXTERNAL_ROOT_PROFILES:
                    roots.append(node)
            except Exception:
                continue
        if not roots:
            self.logger.info(
                "External dependencies: no %s write nodes. Found: %s"
                % (list(_EXTERNAL_ROOT_PROFILES), profiles_found or "none")
            )
            return
        self.logger.info(
            "External dependencies: analysing %s" % ([n.name() for n in roots],)
        )

        session_path = _session_path()
        work_template = parent_item.properties.get("work_template")
        if not session_path or not work_template or not work_template.validate(session_path):
            self.logger.warning(
                "The script path does not match the work template (%s, %s). "
                "External dependencies were not analysed." % (session_path, work_template)
            )
            return
        session_fields = work_template.get_fields(session_path)
        if "Shot" in session_fields:
            prefix = "shot"
        elif "Asset" in session_fields:
            prefix = "asset"
        else:
            return
        version = session_fields.get("version")
        if version is None:
            return

        templates = {
            "camera": tk.templates.get("nuke_%s_camera_publish" % prefix),
            "geo": tk.templates.get("nuke_%s_geo_publish" % prefix),
            "seq": tk.templates.get("external_publish_seq"),
            "file": tk.templates.get("external_publish_file"),
        }
        work_area = tk.templates.get("%s_work_area_nuke" % prefix)
        if not templates["seq"] or not templates["file"] or not work_area:
            self.logger.warning(
                "The templates external_publish_seq / external_publish_file are "
                "missing in templates.yml. External dependencies were not analysed."
            )
            return
        step_root = os.path.normcase(
            os.path.normpath(os.path.dirname(work_area.apply_fields(session_fields)))
        )

        # what is published in EXTERNAL already is part of the pipeline
        external_root = os.path.normcase(os.path.normpath(os.path.dirname(os.path.dirname(
            os.path.dirname(templates["file"].apply_fields(
                {"external_name": "x", "version": 1, "extension": "x"}))))))

        # PRECOMP renders are collected by collect_precomp_reads
        precomp_pairs = [p["work"] for p in self._read_profile_templates()]
        context = parent_item.context
        entity = context.entity if context else None
        tech_dirs = self._get_tech_precomp_dirs()
        project_path = os.path.normcase(os.path.normpath(tk.project_path or ""))

        # ---- the nodes that contribute to the render write nodes
        candidates = {}
        for node in self._walk_render_trees(roots):
            info = self._external_node_info(node)
            if not info:
                continue
            kind, path = info
            norm = os.path.normpath(path)

            if _is_pipeline_path(norm, project_path) or _is_inside(
                os.path.dirname(norm), external_root
            ):
                continue
            if kind == "image" and self._is_precomp_read(
                norm, precomp_pairs, entity, tech_dirs
            ):
                continue

            key = (kind, os.path.normcase(norm))
            if key not in candidates:
                candidates[key] = {"kind": kind, "path": path, "nodes": []}
            candidates[key]["nodes"].append(node)

        if not candidates:
            self.logger.info("External dependencies: nothing outside the pipeline.")
            return

        # ---- build the plans
        fingerprint_field = self._fingerprint_field_exists(tk)
        if not fingerprint_field:
            self.logger.warning(
                "The PublishedFile field '%s' does not exist. The fingerprint is "
                "kept in a file next to the publish instead." % (_FINGERPRINT_FIELD,)
            )
        project = context.project if context else None

        plans = []
        for key in sorted(candidates):
            candidate = candidates[key]
            try:
                plan = self._plan_external(
                    tk, candidate, templates, session_fields, version, step_root,
                    project, fingerprint_field,
                )
            except Exception as e:
                self.logger.warning(
                    "Could not analyse %s: %s" % (candidate["path"], e)
                )
                continue
            if plan:
                plans.append(plan)
        if not plans:
            return

        # ---- drop what is registered in Flow already
        registered = set()
        to_check = [p["publish_path"] for p in plans if not p["relink_only"]]
        if to_check:
            try:
                found = sgtk.util.find_publish(tk, to_check)
                registered = set(os.path.normcase(os.path.normpath(p)) for p in found)
            except Exception as e:
                self.logger.warning("Could not check the registered publishes: %s" % (e,))

        icons = os.path.join(self.disk_location, os.pardir, "icons")
        for plan in plans:
            if (
                not plan["relink_only"]
                and os.path.normcase(os.path.normpath(plan["publish_path"])) in registered
            ):
                plan["relink_only"] = True
                plan["move"] = False

            if "EXTERNAL" not in item_types:
                divider = parent_item.create_item(
                    "nuke.session.external", "EXTERNALS", "All Session EXTERNALS"
                )
                divider.set_icon_from_path(os.path.join(icons, "file.png"))
                divider.expanded = False
                item_types["EXTERNAL"] = divider

            icon, item_type, type_display, publish_type = {
                "images": ("image_sequence.png", "file.external.images", "External Sequence", "EXTERNAL_IMAGES"),
                "file": ("image.png", "file.external.file", "External File", "EXTERNAL_FILE"),
                "camera": ("camera.png", "file.external.camera", "External Camera", None),
                "geo": ("geometry.png", "file.external.geo", "External Geo", None),
            }[plan["item_kind"]]
            if publish_type is None:
                publish_type = _publish_type_for(plan["item_kind"], plan["extension"])

            action = "reconectar" if plan["relink_only"] else ("mover" if plan["move"] else "copiar")
            display_name = "%s [%s] (%s)" % (
                plan["name"], action, ", ".join(sorted(plan["node_names"]))
            )
            item = item_types["EXTERNAL"].create_item(item_type, type_display, display_name)
            item.set_icon_from_path(os.path.join(icons, icon))
            item.thumbnail_enabled = False

            item.properties["publish_type"] = publish_type
            item.properties["path"] = plan["source_path"]
            item.properties["publish_path"] = plan["publish_path"]
            item.properties["publish_name"] = plan["publish_name"]
            item.properties["publish_version"] = plan["version"]
            item.properties["publish_dependencies"] = []
            if fingerprint_field and plan.get("fingerprint"):
                item.properties["publish_fields"] = {_FINGERPRINT_FIELD: plan["fingerprint"]}
            item.properties["external_dependency"] = {
                "relink_only": plan["relink_only"],
                "move": plan["move"],
                "pairs": plan["pairs"],
                "nodes": [n.fullName() for n in plan["nodes"]],
                "sidecar": plan["sidecar"],
                "fingerprint": plan.get("fingerprint"),
                "source_path": plan["source_path"],
            }
            item.context_change_allowed = False
            self.logger.info("Collected external dependency (%s): %s" % (action, plan["source_path"]))

    def _walk_render_trees(self, roots):
        """
        All the nodes that contribute to the given nodes: through inputs,
        expressions and hidden inputs. Groups are entered by their Output nodes,
        the Input nodes of a group continue through the group inputs. LiveGroups
        are not entered.

        :returns: List of nodes
        """
        flags = nuke.INPUTS | nuke.EXPRESSIONS | nuke.HIDDEN_INPUTS
        visited = set()
        found = []
        stack = list(roots)
        while stack:
            node = stack.pop()
            try:
                key = node.fullName()
            except Exception:
                continue
            if key in visited:
                continue
            visited.add(key)
            found.append(node)
            try:
                cls = node.Class()
                if cls == "Input":
                    parent = node.parent()
                    if parent is not None and parent.Class() != "Root":
                        upstream = parent.input(int(node["number"].value()))
                        if upstream is not None:
                            stack.append(upstream)
                elif isinstance(node, nuke.Group) and cls not in ("LiveGroup", "Root"):
                    with node:
                        stack.extend(nuke.allNodes("Output"))
                stack.extend(node.dependencies(flags))
            except Exception as e:
                self.logger.debug("Could not follow '%s': %s" % (key, e))
        return found

    def _external_node_info(self, node):
        """
        :returns: (kind, normalised file path) when the node reads an external
            file, otherwise None. Kind is image, camera or geo.
        """
        try:
            cls = node.Class()
            if cls.startswith("ReadGeo"):
                kind = "geo"
            elif cls == "Read":
                kind = "image"
            elif node.knob("read_from_file") is not None and node.knob("file") is not None:
                if not node["read_from_file"].value():
                    return None
                kind = "camera"
            else:
                return None
            disable = node.knob("disable")
            if disable is not None and disable.value():
                return None
            path = _read_file_path(node)
        except Exception as e:
            self.logger.debug("Could not evaluate '%s': %s" % (node.name(), e))
            return None
        if not path:
            return None
        return kind, path

    def _is_precomp_read(self, path, precomp_templates, entity, tech_dirs):
        """
        True when the Read points at a PRECOMP of the current entity, those are
        collected by collect_precomp_reads (or by their TECH_PRECOMP write node).
        """
        for template in precomp_templates:
            if template.validate(path):
                fields = template.get_fields(path)
                if entity and fields.get(entity["type"]) not in (None, entity.get("name")):
                    return False
                return True
        return os.path.normcase(os.path.dirname(path)) in tech_dirs

    def _fingerprint_field_exists(self, tk):
        try:
            return _FINGERPRINT_FIELD in tk.shotgun.schema_field_read("PublishedFile")
        except Exception as e:
            self.logger.debug("Could not read the PublishedFile schema: %s" % (e,))
            return False

    def _plan_external(self, tk, candidate, templates, session_fields, version,
                       step_root, project, fingerprint_field):
        """
        Work out what has to be done with one external file or sequence.

        :returns: Dictionary describing it or None when there is nothing to do
        """
        kind = candidate["kind"]
        path = candidate["path"]
        nodes = candidate["nodes"]
        node_names = [n.name() for n in nodes]
        is_sequence = bool(re.search(r"%\d*d", os.path.basename(path)))

        # ---- the files on disk
        if is_sequence:
            frames = self._find_sequence_files(path)
            lows, highs = [], []
            for node in nodes:
                try:
                    lows.append(int(node["origfirst"].value()))
                    highs.append(int(node["origlast"].value()))
                except Exception:
                    pass
            if lows:
                used = [f for f in frames if min(lows) <= f[0] <= max(highs)]
                frames = used or frames
            if not frames:
                self.logger.info("No frames on disk, skipping: %s" % (path,))
                return None
            sources = [f[1] for f in frames]
            numbers = [f[0] for f in frames]
        else:
            if not os.path.isfile(path):
                self.logger.info("The file does not exist, skipping: %s" % (path,))
                return None
            sources = [path]
            numbers = []

        move = all(_is_inside(os.path.dirname(s), step_root) for s in sources)
        fingerprint = _fingerprint_files(sources)

        plan = {
            "nodes": nodes,
            "node_names": node_names,
            "source_path": path,
            "fingerprint": fingerprint,
            "sidecar": False,
            "relink_only": False,
            "move": move,
            "pairs": [],
        }

        if kind in ("camera", "geo"):
            ext = os.path.splitext(path)[1].lstrip(".")
            template = templates[kind]
            if not template:
                return None
            name = _alnum(sorted(node_names)[0]) or kind
            fields = dict(session_fields)
            fields.update({"name": name, "version": version, "extension": ext})
            if template.missing_keys(fields):
                self.logger.warning("Missing keys for the %s publish template: %s" % (kind, path))
                return None
            publish_path = template.apply_fields(fields)
            plan.update({
                "item_kind": kind,
                "extension": ext,
                "name": name,
                "version": version,
                "publish_name": "%s %s" % (name, "Camera" if kind == "camera" else "Geo"),
                "publish_path": publish_path,
                "pairs": [(sources[0], publish_path)],
            })
            if os.path.exists(publish_path):
                if os.path.getsize(publish_path) != os.path.getsize(sources[0]):
                    self.logger.warning(
                        "%s already exists and is a different file than %s. "
                        "Skipping it." % (publish_path, path)
                    )
                    return None
                # published (or half published) before: just reconnect
                plan["relink_only"] = True
                plan["move"] = False
                plan["pairs"] = []
            return plan

        # ---- image sequence / file: EXTERNAL/<name>/v###
        if is_sequence:
            base, ext = _split_sequence_name(path)
            template = templates["seq"]
        else:
            base, ext = os.path.splitext(os.path.basename(path))
            ext = ext.lstrip(".")
            template = templates["file"]
        name = _sanitize_name(base)
        fields = {"external_name": name, "extension": ext}
        if is_sequence:
            fields["SEQ"] = "%04d"

        existing = self._find_existing_external(
            tk, template, fields, fingerprint, project, fingerprint_field
        )
        plan.update({
            "item_kind": "images" if is_sequence else "file",
            "extension": ext,
            "name": name,
            "publish_name": name,
        })
        if existing:
            plan.update({
                "version": existing[0],
                "publish_path": existing[1],
                "relink_only": True,
                "move": False,
            })
            return plan

        next_version = self._next_external_version(template, fields)
        fields["version"] = next_version
        publish_path = template.apply_fields(fields)
        plan.update({
            "version": next_version,
            "publish_path": publish_path,
            "sidecar": True,
        })
        if is_sequence:
            folder = os.path.dirname(publish_path)
            plan["pairs"] = [
                (src, os.path.join(folder, "%s.%04d.%s" % (name, num, ext)))
                for src, num in zip(sources, numbers)
            ]
        else:
            plan["pairs"] = [(sources[0], publish_path)]
        return plan

    def _external_base_dir(self, template, fields):
        probe = dict(fields)
        probe["version"] = 1
        return os.path.dirname(os.path.dirname(template.apply_fields(probe)))

    def _next_external_version(self, template, fields):
        base_dir = self._external_base_dir(template, fields)
        highest = 0
        try:
            for entry in os.listdir(base_dir):
                match = re.match(r"^v(\d+)$", entry, re.IGNORECASE)
                if match:
                    highest = max(highest, int(match.group(1)))
        except OSError:
            pass
        return highest + 1

    def _find_existing_external(self, tk, template, fields, fingerprint, project, fingerprint_field):
        """
        Look for an EXTERNAL publish with the same content.

        :returns: (version, publish path) or None
        """
        # 1. the fingerprint field in Flow (any name: same content, same publish)
        if fingerprint_field:
            try:
                filters = [[_FINGERPRINT_FIELD, "is", fingerprint]]
                if project:
                    filters.insert(0, ["project", "is", project])
                for publish in tk.shotgun.find(
                    "PublishedFile", filters, ["path", "path_cache", "version_number"],
                    order=[{"field_name": "id", "direction": "asc"}],
                ):
                    path = sgtk.util.resolve_publish_path(tk, publish)
                    if path and os.path.exists(os.path.dirname(path.replace("%04d", "0000"))):
                        return publish.get("version_number") or 1, path
            except Exception as e:
                self.logger.warning("Could not search by fingerprint in Flow: %s" % (e,))

        # 2. the fingerprint file next to the publishes of that name
        base_dir = self._external_base_dir(template, fields)
        try:
            entries = os.listdir(base_dir)
        except OSError:
            return None
        for entry in sorted(entries):
            match = re.match(r"^v(\d+)$", entry, re.IGNORECASE)
            sidecar = os.path.join(base_dir, entry, _FINGERPRINT_SIDECAR)
            if not match or not os.path.isfile(sidecar):
                continue
            try:
                with open(sidecar, "r") as handle:
                    if handle.readline().strip() != fingerprint:
                        continue
            except (OSError, IOError):
                continue
            probe = dict(fields)
            probe["version"] = int(match.group(1))
            return int(match.group(1)), template.apply_fields(probe)
        return None

    def collect_sg_writeGeoCam_nodes(self, parent_item, item_types):
        """
        Collect any rendered sg write nodes in the session.

        :param parent_item:  The parent item for any sg write nodes collected
        """

        publisher = self.parent
        engine = publisher.engine

        first_frame = int(nuke.root()["first_frame"].value())
        last_frame = int(nuke.root()["last_frame"].value())

        for node in nuke.allNodes("ShotgunWriteCam.gizmo"):

            self.logger.info(str(node))
            # if 'PRECOMP' not in node.knob('tk_profile_list').value():
            # if item.context.entity == 'Asset':
            # see if any frames have been rendered for this write node
            rendered_files = []
            try:
                for file in os.listdir(os.path.dirname(node['Path'].value())):
                    full_path = os.path.normpath(os.path.join(os.path.dirname(node['Path'].value()), file))
                    if os.path.isfile(full_path):
                        pattern = os.path.normpath(node['Path'].value()[:node['Path'].value().find('_v')+5])
                        if pattern in os.path.normpath(full_path):
                            rendered_files.append(full_path)
            except:
                self.logger.info("No renders found for node '%s'" % (node['name'].value()))
                continue

            if len(rendered_files) == 0:
                continue

            # some files rendered, use first frame to get some publish item info
            path = rendered_files[0]
            item_info = super(NukeSessionCollector, self)._get_item_info(path)

            # item_info will be for the single file. we'll update the type and
            # display to represent a sequence. This is the same pattern used by
            # the base collector for image sequences. We're not using the base
            # collector to create the publish item though since we already have
            # the sequence path, template knowledge provided by the
            # tk-nuke-writenode app. The base collector makes some "zero config"
            # assupmtions about the path that we don't need to make here.
            item_type = "nuke.camera"
            type_display = "Camera"

            # we'll publish the path with the frame/eye spec (%V, %04d)
            render_path = node['Path'].value()
            publish_path = node['Publish_path'].value()

            # construct publish name:
            node_work_template_node = node['work_template'].value()
            tk = engine.sgtk
            render_template = tk.templates[node_work_template_node]
            render_path_fields = render_template.get_fields(render_path)

            node_publish_template_node = node['publish_template'].value()
            publish_template = tk.templates[node_publish_template_node]
            publish_path_fields = publish_template.get_fields(publish_path)

            # rp_name = publish_path_fields.get("name")
            # rp_channel = publish_path_fields.get("channel")
            # if not rp_name and not rp_channel:
            #     publish_name = "%s %s" %(node.knob('tk_profile_list').value(), node.knob('tank_channel').value())
            # elif not rp_name:
            #     publish_name = "Channel %s" % rp_channel
            # elif not rp_channel:
            #     publish_name = rp_name
            # else:
            #     publish_name = "%s, Channel %s" % (rp_name, rp_channel)

            publish_name = "%s %s %s" % ('_'.join(os.path.splitext(os.path.basename(publish_path))[0].split('_')[:-1]), publish_path_fields.get("name"), "Camera")

            # get the version number from the render path
            version_number = publish_path_fields.get("version")

            # use the path basename and nuke writenode name for display
            (_, filename) = os.path.split(publish_path)
            display_name = "%s (%s) %s" % ("Camera Publish", publish_name, node.name())

            # create and populate the item
            item = parent_item.create_item(item_type, type_display, display_name)
            icon_path = os.path.join(self.disk_location, os.pardir, "icons", "camera.png")
            item.set_icon_from_path(icon_path)

            # if the supplied path is an image, use the path as # the thumbnail.
            item.set_thumbnail_from_path(path)

            # disable thumbnail creation since we get it for free
            item.thumbnail_enabled = False

            # all we know about the file is its path. set the path in its
            # properties for the plugins to use for processing.
            item.properties["path"] = render_path
            item.properties["publish_path"] = publish_path

            # include an indicator that this is an image sequence and the known
            # file that belongs to this sequence
            item.properties["sequence_paths"] = rendered_files

            # store publish info on the item so that the base publish plugin
            # doesn't fall back to zero config path parsing
            item.properties["publish_name"] = publish_name
            item.properties["publish_version"] = version_number
            item.properties[
                "publish_template"
            ] = publish_template
            item.properties[
                "work_template"
            ] = render_template
            item.properties["first_frame"] = first_frame
            item.properties["last_frame"] = last_frame
            item.properties["publish_fields"] = {'sg_status_list': 'cmpt'}

            # store the nuke writenode on the item as well. this can be used by
            # secondary publish plugins
            item.properties["sg_writenode"] = node

            # Collect dependencies from node
            item.properties["publish_dependencies"] = self.list_dependencies(node)

            # we have a publish template so disable context change. This
            # is a temporary measure until the publisher handles context
            # switching natively.
            item.context_change_allowed = False

            self.logger.info("Collected file: %s" % (publish_path,))

    def collect_sg_writeGeo_nodes(self, parent_item, item_types):
        """
        Collect any rendered sg write nodes in the session.

        :param parent_item:  The parent item for any sg write nodes collected
        """

        publisher = self.parent
        engine = publisher.engine

        first_frame = int(nuke.root()["first_frame"].value())
        last_frame = int(nuke.root()["last_frame"].value())

        for node in nuke.allNodes("ShotgunWriteGeo.gizmo"):

            self.logger.info(str(node))
            # if 'PRECOMP' not in node.knob('tk_profile_list').value():
            # if item.context.entity == 'Asset':
            # see if any frames have been rendered for this write node
            rendered_files = []
            try:
                for file in os.listdir(os.path.dirname(node['Path'].value())):
                    full_path = os.path.normpath(os.path.join(os.path.dirname(node['Path'].value()), file))
                    if os.path.isfile(full_path):
                        pattern = os.path.normpath(node['Path'].value()[:node['Path'].value().find('_v') + 5])
                        if pattern in os.path.normpath(full_path):
                            rendered_files.append(full_path)
            except:
                self.logger.info("No renders found for node '%s'" % (node['name'].value()))
                continue

            if len(rendered_files) == 0:
                continue

            # some files rendered, use first frame to get some publish item info
            path = rendered_files[0]
            item_info = super(NukeSessionCollector, self)._get_item_info(path)

            # item_info will be for the single file. we'll update the type and
            # display to represent a sequence. This is the same pattern used by
            # the base collector for image sequences. We're not using the base
            # collector to create the publish item though since we already have
            # the sequence path, template knowledge provided by the
            # tk-nuke-writenode app. The base collector makes some "zero config"
            # assupmtions about the path that we don't need to make here.
            item_type = "nuke.geo"
            type_display = "Geometry"

            # we'll publish the path with the frame/eye spec (%V, %04d)
            render_path = node['Path'].value()
            publish_path = node['Publish_path'].value()

            # construct publish name:
            node_work_template_node = node['work_template'].value()
            tk = engine.sgtk
            render_template = tk.templates[node_work_template_node]
            render_path_fields = render_template.get_fields(render_path)

            node_publish_template_node = node['publish_template'].value()
            publish_template = tk.templates[node_publish_template_node]
            publish_path_fields = publish_template.get_fields(publish_path)

            # rp_name = publish_path_fields.get("name")
            # rp_channel = publish_path_fields.get("channel")
            # if not rp_name and not rp_channel:
            #     publish_name = "Publish"
            # elif not rp_name:
            #     publish_name = "Channel %s" % rp_channel
            # elif not rp_channel:
            #     publish_name = rp_name
            # else:
            #     publish_name = "%s, Channel %s" % (rp_name, rp_channel)

            publish_name = "%s %s %s" % ('_'.join(os.path.splitext(os.path.basename(publish_path))[0].split('_')[:-1]), publish_path_fields.get("name"), "Geometry")

            # get the version number from the render path
            version_number = publish_path_fields.get("version")

            # use the path basename and nuke writenode name for display
            (_, filename) = os.path.split(publish_path)
            display_name = "%s (%s) %s" % ("Camera Publish", publish_name, node.name())

            # create and populate the item
            item = parent_item.create_item(item_type, type_display, display_name)
            item.set_icon_from_path(item_info["icon_path"])

            # if the supplied path is an image, use the path as # the thumbnail.
            item.set_thumbnail_from_path(path)

            # disable thumbnail creation since we get it for free
            item.thumbnail_enabled = False

            # all we know about the file is its path. set the path in its
            # properties for the plugins to use for processing.
            item.properties["path"] = render_path
            item.properties["publish_path"] = publish_path

            # include an indicator that this is an image sequence and the known
            # file that belongs to this sequence
            item.properties["sequence_paths"] = rendered_files

            # store publish info on the item so that the base publish plugin
            # doesn't fall back to zero config path parsing
            item.properties["publish_name"] = publish_name
            item.properties["publish_version"] = version_number
            item.properties[
                "publish_template"
            ] = publish_template
            item.properties[
                "work_template"
            ] = render_template
            item.properties["first_frame"] = first_frame
            item.properties["last_frame"] = last_frame
            item.properties["publish_fields"] = {'sg_status_list': 'cmpt'}

            # store the nuke writenode on the item as well. this can be used by
            # secondary publish plugins
            item.properties["sg_writenode"] = node

            #Collect dependencies from node
            item.properties["publish_dependencies"] = self.list_dependencies(node)


            # we have a publish template so disable context change. This
            # is a temporary measure until the publisher handles context
            # switching natively.
            item.context_change_allowed = False

            self.logger.info("Collected file: %s" % (publish_path,))

    def _get_node_colorspace(self, node):
        """
        Get the colorspace for the specified nuke node

        :param node:    The nuke node to find the colorspace for
        :returns:       The string representing the colorspace for the node
        """
        cs_knob = node.knob("colorspace")
        if not cs_knob:
            return

        cs = cs_knob.value()
        # handle default value where cs would be something like: 'default (linear)'
        if cs.startswith("default (") and cs.endswith(")"):
            cs = cs[9:-1]
        return cs

    def list_dependencies(self, node):
        nodeslist = []

        def select_node_dependencies_recursive(node):
            if node.Class() in ['Read', 'Camera2', 'ReadGeo2']:
                file_path = node['file'].value()
                if not file_path:
                    pass
                else:
                    if node['file'].value() not in nodeslist:
                        nodeslist.append(node['file'].value())
            for dep in node.dependencies(nuke.INPUTS):
                try:
                    select_node_dependencies_recursive(dep)
                except:
                    print("WARNING: there was a problem with %s, please check" % dep.name())

        select_node_dependencies_recursive(node)
        return nodeslist



def _mp4_frame_count(path):
    import struct

    def boxes(f, start, end):
        pos = start
        while pos + 8 <= end:
            f.seek(pos)
            hdr = f.read(8)
            if len(hdr) < 8:
                return
            size, typ = struct.unpack(">I4s", hdr)
            hlen = 8
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
                hlen = 16
            elif size == 0:
                size = end - pos
            if size < hlen:
                return
            yield typ, pos + hlen, pos + size
            pos += size

    with open(path, "rb") as f:
        f.seek(0, 2)
        fsize = f.tell()
        for typ, s, e in boxes(f, 0, fsize):
            if typ != b"moov":
                continue
            for t2, s2, e2 in boxes(f, s, e):
                if t2 != b"trak":
                    continue
                is_video, count = False, None
                for t3, s3, e3 in boxes(f, s2, e2):
                    if t3 != b"mdia":
                        continue
                    for t4, s4, e4 in boxes(f, s3, e3):
                        if t4 == b"hdlr":
                            f.seek(s4 + 8)
                            is_video = f.read(4) == b"vide"
                        elif t4 == b"minf":
                            for t5, s5, e5 in boxes(f, s4, e4):
                                if t5 != b"stbl":
                                    continue
                                for t6, s6, e6 in boxes(f, s5, e5):
                                    if t6 == b"stts":
                                        f.seek(s6 + 4)
                                        n = struct.unpack(">I", f.read(4))[0]
                                        count = 0
                                        for _ in range(n):
                                            c, _d = struct.unpack(">II", f.read(8))
                                            count += c
                if is_video and count:
                    return count
    return None


def _exr_is_32bit_float(path):
    """
    True when the file is an OpenEXR whose channels are all 32 bit float. Only
    the header (first few KB, no pixels) is read. Any other file or any problem
    gives False.
    """
    import struct
    try:
        with open(path, "rb") as handle:
            data = handle.read(65536)
        if data[:4] != b"\x76\x2f\x31\x01":
            return False
        pos = 8
        while pos < len(data) and data[pos:pos + 1] != b"\x00":
            end = data.index(b"\x00", pos)
            name = data[pos:end].decode("ascii", "replace")
            pos = end + 1
            end = data.index(b"\x00", pos)
            pos = end + 1
            size = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            if name == "channels":
                value = data[pos:pos + size]
                types = []
                i = 0
                while i < len(value) and value[i:i + 1] != b"\x00":
                    i = value.index(b"\x00", i) + 1
                    types.append(struct.unpack("<i", value[i:i + 4])[0])
                    i += 16
                return bool(types) and all(t == 2 for t in types)
            pos += size
    except Exception:
        return False
    return False


def _is_inside(folder, root):
    """True when the folder is root or lives under it (case-insensitive on Windows)."""
    folder = os.path.normcase(os.path.normpath(folder))
    return folder == root or folder.startswith(root + os.sep)


def _is_pipeline_path(path, project_path):
    """
    True for the files that already belong to the pipeline and are never
    touched: anything under SOURCE, VREF or PUBLISH inside the project.
    """
    norm = os.path.normcase(os.path.normpath(path))
    if not project_path or not _is_inside(os.path.dirname(norm), project_path):
        return False
    relative = norm[len(project_path):]
    parts = [p for p in re.split(r"[\\/]+", relative) if p]
    return any(p.lower() in _PIPELINE_FOLDERS for p in parts[:-1])


def _split_sequence_name(path):
    """
    ``/a/shot_plate.%04d.exr`` -> (``shot_plate``, ``exr``). Without a prefix the
    name of the folder is used.
    """
    folder, pattern = os.path.split(path)
    spec = re.search(r"%\d*d", pattern)
    if not spec:
        base, ext = os.path.splitext(pattern)
        return base, ext.lstrip(".")
    base = pattern[: spec.start()].rstrip("._- ")
    if not base:
        base = os.path.basename(folder)
    return base, pattern[spec.end():].lstrip(".")


def _sanitize_name(name):
    """Keep letters, digits, ``_``, ``-`` and ``.``. The rest becomes ``_``."""
    cleaned = re.sub(r"[^A-Za-z0-9_.\-]+", "_", name or "").strip("._")
    return cleaned or "external"


def _alnum(name):
    """The ``name`` template key only accepts letters and digits."""
    return re.sub(r"[^A-Za-z0-9]+", "", name or "")


def _publish_type_for(item_kind, extension):
    ext = (extension or "").lower()
    if item_kind == "camera":
        return {"abc": "Alembic Camera", "fbx": "FBX Camera"}.get(
            ext, "%s File" % ext.capitalize() if ext else "Folder"
        )
    return {
        "obj": "Obj File", "mxf": "MXF File", "abc": "Alembic Cache",
        "fbx": "Motion Builder FBX",
    }.get(ext, "%s File" % ext.capitalize() if ext else "Folder")


def _fingerprint_files(files):
    """
    Content fingerprint of a file or sequence: number of files, the size of all
    of them and a few chunks of the first, middle and last file.
    """
    files = list(files)
    digest = hashlib.sha1()
    digest.update(("n=%d;" % len(files)).encode("utf-8"))
    sizes = []
    for path in files:
        try:
            sizes.append(os.path.getsize(path))
        except OSError:
            sizes.append(-1)
    digest.update(",".join(str(s) for s in sizes).encode("utf-8"))
    chunk = 65536
    for index in sorted(set([0, len(files) // 2, len(files) - 1])):
        if index < 0 or index >= len(files):
            continue
        size = sizes[index]
        try:
            with open(files[index], "rb") as handle:
                digest.update(handle.read(chunk))
                if size > 3 * chunk:
                    handle.seek(size // 2)
                    digest.update(handle.read(chunk))
                    handle.seek(size - chunk)
                    digest.update(handle.read(chunk))
        except (OSError, IOError):
            continue
    return "fp1-" + digest.hexdigest()


def _read_file_path(node):
    """
    The file of a Read-like node with the frame spec kept (``%04d``).

    ``knob.evaluate()`` can return the path with the current frame already
    replaced (``name.0000.exr``), which hides that it is a sequence, so the
    raw value is used unless it holds TCL/expressions.
    """
    knob = node["file"]
    value = knob.value()
    if value and "[" not in value and "$" not in value:
        return _normalize_sequence_path(value)
    return _normalize_sequence_path(knob.evaluate())


def _normalize_sequence_path(path):
    """
    Return the path with forward slashes and the frame spec as ``%0Nd``
    (Nuke accepts ``####`` too).
    """
    if not path:
        return path
    path = path.replace("\\", "/")
    return re.sub(r"#+", lambda m: "%%0%dd" % len(m.group(0)), path)


def _session_path():
    """
    Return the path to the current session
    :return:
    """
    root_name = nuke.root().name()
    return None if root_name == "Root" else root_name
