# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import glob
import os
import maya.cmds as cmds
import maya.mel as mel
import sgtk
import fnmatch
from tank_vendor import six

HookBaseClass = sgtk.get_hook_baseclass()


class MayaSessionCollector(HookBaseClass):
    """
    Collector that operates on the maya session. Should inherit from the basic
    collector hook.
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
        collector_settings = super(MayaSessionCollector, self).settings or {}

        # settings specific to this collector
        maya_session_settings = {
            "Work Template": {
                "type": "template",
                "default": None,
                "description": "Template path for artist work files. Should "
                "correspond to a template defined in "
                "templates.yml. If configured, is made available"
                "to publish plugins via the collected item's "
                "properties. ",
            },
            "Cameras": {
                "type": "list",
                "default": ["camera*"],
                "description": "Glob-style list of camera names to publish. "
                               "Example: ['camMain', 'camAux*']."
            }
        }

        # update the base settings with these settings
        collector_settings.update(maya_session_settings)

        return collector_settings

    def process_current_session(self, settings, parent_item):
        """
        Analyzes the current session open in Maya and parents a subtree of
        items under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance

        """

        # create an item representing the current maya session
        item, work_template = self.collect_current_maya_session(settings, parent_item)
        project_root = item.properties["project_root"]
        item_types = {}



        # if we can determine a project root, collect other files to publish
        if project_root:

            self.logger.info(
                "Current Maya project is: %s." % (project_root,),
                extra={
                    "action_button": {
                        "label": "Change Project",
                        "tooltip": "Change to a different Maya project",
                        "callback": lambda: mel.eval('setProject ""'),
                    }
                },
            )

            # self.collect_playblasts(item, project_root)
            # self.collect_playblastsSeq(item, project_root)
            # self.collect_alembic_caches(item, project_root)
        else:

            self.logger.info(
                "Could not determine the current Maya project.",
                extra={
                    "action_button": {
                        "label": "Set Project",
                        "tooltip": "Set the Maya project",
                        "callback": lambda: mel.eval('setProject ""'),
                    }
                },
            )

        # if cmds.ls(geometry=True, noIntermediate=True):
        #     self._collect_session_geometry(item)

        # self._collect_meshes(item)
        # look at the render layers to find rendered images on disk
        self.collect_rendered_images(item, item_types, work_template)
        self._collect_cameras(settings, item, item_types, work_template)
        self._collect_object_geo_group(item, item_types, work_template)
        self._collect_object_geo(item, item_types, work_template)
        # self._collect_object_sets(parent_item, item_types, work_template)
        self._collect_particles_geo(item, item_types, work_template)
        self._collect_ass(item, item_types, work_template)
        self._collect_vdb(item, item_types, work_template)

    def collect_current_maya_session(self, settings, parent_item):
        """
        Creates an item that represents the current maya session.

        :param parent_item: Parent Item instance

        :returns: Item of type maya.session
        """

        publisher = self.parent

        # get the path to the current file
        path = cmds.file(query=True, sn=True)

        # determine the display name for the item
        if path:
            file_info = publisher.util.get_file_path_components(path)
            display_name = file_info["filename"]
        else:
            display_name = "Current Maya Session"

        # create the session item for the publish hierarchy
        session_item = parent_item.create_item(
            "maya.session", "Maya Session", display_name
        )

        # get the icon path to display for this item
        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "maya.png")
        session_item.set_icon_from_path(icon_path)

        # discover the project root which helps in discovery of other
        # publishable items
        project_root = cmds.workspace(q=True, rootDirectory=True)
        session_item.properties["project_root"] = project_root

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
            work_fields = work_template.get_fields(path)
            publish_name = str(work_fields["name"]) + "_" + str(work_fields["Step"])
            session_item.properties["publish_name"] = publish_name
            session_item.properties["path"] = sgtk.util.ShotgunPath.normalize(path)
            self.logger.debug("Work template defined for Maya collection.")

        self.logger.info("Collected current Maya scene")

        return session_item, work_template

    # def collect_alembic_caches(self, parent_item, project_root):
    #     """
    #     Creates items for alembic caches
    #
    #     Looks for a 'project_root' property on the parent item, and if such
    #     exists, look for alembic caches in a 'cache/alembic' subfolder.
    #
    #     :param parent_item: Parent Item instance
    #     :param str project_root: The maya project root to search for alembics
    #     """
    #
    #     # ensure the alembic cache dir exists
    #     cache_dir = os.path.join(project_root, "cache", "alembic")
    #     if not os.path.exists(cache_dir):
    #         return
    #
    #     self.logger.info(
    #         "Processing alembic cache folder: %s" % (cache_dir,),
    #         extra={"action_show_folder": {"path": cache_dir}},
    #     )
    #
    #     # look for alembic files in the cache folder
    #     for filename in os.listdir(cache_dir):
    #         cache_path = os.path.join(cache_dir, filename)
    #
    #         # do some early pre-processing to ensure the file is of the right
    #         # type. use the base class item info method to see what the item
    #         # type would be.
    #         item_info = self._get_item_info(filename)
    #         if item_info["item_type"] != "file.alembic":
    #             continue
    #
    #         # allow the base class to collect and create the item. it knows how
    #         # to handle alembic files
    #         item = super(MayaSessionCollector, self)._collect_file(parent_item, cache_path)
    #         item.properties["type_spec"] = "file.alembic"
    #         item.properties["object_name"] = filename


    # def collect_playblasts(self, parent_item, project_root):
    #     """
    #     Creates items for quicktime playblasts.
    #
    #     Looks for a 'project_root' property on the parent item, and if such
    #     exists, look for movie files in a 'movies' subfolder.
    #
    #     :param parent_item: Parent Item instance
    #     :param str project_root: The maya project root to search for playblasts
    #     """
    #
    #     movie_dir_name = None
    #     path = cmds.file(query=True, sn=True)
    #     work_template = parent_item.properties.get("work_template")
    #     work_fields = work_template.get_fields(path)
    #     version = "_v" + str("{:03d}".format(work_fields["version"]))
    #
    #     # try to query the file rule folder name for movies. This will give
    #     # us the directory name set for the project where movies will be
    #     # written
    #     if "movie" in cmds.workspace(fileRuleList=True):
    #         # this could return an empty string
    #         movie_dir_name = cmds.workspace(fileRuleEntry="movie")
    #
    #     if not movie_dir_name:
    #         # fall back to the default
    #         movie_dir_name = "movies"
    #
    #     # ensure the movies dir exists
    #     movies_dir = os.path.join(project_root, movie_dir_name)
    #     if not os.path.exists(movies_dir):
    #         return
    #
    #     self.logger.info(
    #         "Processing movies folder: %s" % (movies_dir,),
    #         extra={"action_show_folder": {"path": movies_dir}},
    #     )
    #
    #     # look for movie files in the movies folder
    #     for filename in os.listdir(movies_dir):
    #         if version in filename and "PLAYBLAST" in filename:
    #             # do some early pre-processing to ensure the file is of the right
    #             # type. use the base class item info method to see what the item
    #              # type would be.
    #         item_info = self._get_item_info(filename)
    #         if item_info["item_type"] != "file.video":
    #             continue
    #         if version in filename and "PLAYBLAST" in filename:
    #             playblastSeq_path = glob.glob(os.path.join(imagesDir, filename))
    #
    #             # allow the base class to collect and create the item. it knows how
    #             # to handle movie files
    #             item = super(MayaSessionCollector, self)._collect_file(
    #                 parent_item, playblastSeq_path[0], frame_sequence=True
    #             )
    #
    #             # the item has been created. update the display name to include
    #             # the an indication of what it is and why it was collected
    #             item.name = "%s (%s)" % (item.name, "playblastSeq")
    #             item.type_spec = "maya.session.playblastSeq"
    #             item.properties["sequence_paths"] = playblastSeq_path



    def collect_rendered_images(self, parent_item, item_types, work_template):
        """
        Creates items for any rendered images that can be identified by
        render layers in the file.

        :param parent_item: Parent Item instance
        :return:
        """

        # iterate over defined render layers and query the render settings for
        # information about a potential render
        layerList = []

        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "image_sequence.png")


        for layer in cmds.ls(type="renderLayer"):
            # layerFixed = cmds.renderSetup(q=True, renderLayers=True)


            self.logger.info("Processing render layer: %s" % (layer,))
            renderable_cameras = cmds.ls(type="camera")
            renderable_cameras = [cam for cam in renderable_cameras if cmds.getAttr(cam + ".renderable")]
            for cam in renderable_cameras:
                if "camMain" in cam:

                    # use the render settings api to get a path where the frame number
                    # spec is replaced with a '*' which we can use to glob
                    (frame_glob,) = cmds.renderSettings(
                        genericFrameImageName="*", fullPath=True, layer=layer, camera=cam)
                    if frame_glob not in layerList:
                        layerList.append(frame_glob)
                        # see if there are any files on disk that match this pattern
                        rendered_paths = glob.glob(frame_glob)

                        if rendered_paths:

                            if "renders" not in item_types:
                                renderdivider = parent_item.create_item("maya.session.renders", "Renders",
                                                                     "All Session Renders")
                                renderdivider.set_icon_from_path(icon_path)
                                renderdivider.expanded = False
                                item_types["renders"] = renderdivider
                                renderdivider.properties["work_template"] = work_template

                            # we only need one path to publish, so take the first one and
                            # let the base class collector handle it
                            item = super(MayaSessionCollector, self)._collect_file(
                                item_types["renders"], rendered_paths[0], frame_sequence=True
                            )

                            # the item has been created. update the display name to include
                            # the an indication of what it is and why it was collected
                            item.name = "%s (Render Layer: %s)" % (item.name, layer)
                            item.properties["sequence_paths"] = rendered_paths
                            item.type_spec = "maya.session.render"
                            item.properties["publish_type"] = "RENDER_MAYA"
                            item.properties["work_template"] = work_template
                            stringLayer = layer
                            if layer.startswith("rs_"):
                                stringLayer = layer[3:]

                            if "masterLayer" in rendered_paths[0]:
                                item.properties["maya.layer_name"] = "masterLayer"
                            else:
                                item.properties["maya.layer_name"] = stringLayer

                            item.properties["path"] = rendered_paths[0]

                            work_fields = work_template.get_fields(_session_path())

                            # include the extension in the fields
                            filename, extension = os.path.splitext(rendered_paths[0])
                            work_fields["extension"] = extension[1:]
                            work_fields["frame_num"] = 6969
                            work_fields["maya.layer_name"] = item.properties["maya.layer_name"]
                            work_fields["maya.camera_name"] = cam
                            item.properties["work_fields"] = work_fields
                            item.properties["publish_version"] = work_fields["version"]
                            self.logger.info("collecting render layer %s", item.properties["maya.layer_name"])

    # def _collect_meshes(self, parent_item):
    #     """
    #     Collect mesh definitions and create publish items for them.
    #
    #     :param parent_item: The maya session parent item
    #     """
    #
    #     # build a path for the icon to use for each item. the disk
    #     # location refers to the path of this hook file. this means that
    #     # the icon should live one level above the hook in an "icons"
    #     # folder.
    #     icon_path = os.path.join(self.disk_location, os.pardir, "icons", "shading.png")
    #
    #     # iterate over all top-level transforms and create mesh items
    #     # for any mesh.
    #     for object in cmds.ls(assemblies=True):
    #
    #         if not cmds.ls(object, dag=True, type="mesh"):
    #             # ignore non-meshes
    #             continue
    #
    #         # create a new item parented to the supplied session item. We
    #         # define an item type (maya.session.mesh) that will be
    #         # used by an associated shader publish plugin as it searches for
    #         # items to act upon. We also give the item a display type and
    #         # display name (the group name). In the future, other publish
    #         # plugins might attach to these mesh items to publish other things
    #         mesh_item = parent_item.create_item("maya.session.mesh", "Mesh", object)
    #
    #         # set the icon for the item
    #         mesh_item.set_icon_from_path(icon_path)
    #
    #         # finally, add information to the mesh item that can be used
    #         # by the publish plugin to identify and export it properly
    #         mesh_item.properties["object"] = object

    def _collect_cameras(self, settings, parent_item, item_types, work_template):
        """
        Creates items for each camera in the session.

        :param parent_item: The maya session parent item
        """

        # build a path for the icon to use for each item. the disk
        # location refers to the path of this hook file. this means that
        # the icon should live one level above the hook in an "icons"
        # folder.
        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "camera.png")

        # iterate over each camera and create an item for it
        for camera_shape in cmds.ls(cameras=True):

            # try to determine the camera display name
            try:
                camera_name = cmds.listRelatives(camera_shape, parent=True)[0].split(":")[0]

            except Exception:
                # could not determine the name, just use the shape
                try:
                    camera_name = camera_shape.split(":")[0]
                except:
                    camera_name = camera_shape

            if camera_name and camera_shape:
                if not self._cam_name_matches_settings(camera_name, settings):
                    self.logger.info(
                        "Camera name %s does not match any of the configured "
                        "patterns for camera names to publish. Not accepting "
                        "session camera item." % (camera_name,)
                    )
                    continue


            if "cameras" not in item_types:
                camdivider = parent_item.create_item("maya.session.cameras", "Cameras",
                                                     "All Session Cameras")
                camdivider.set_icon_from_path(icon_path)
                camdivider.expanded = False
                item_types["cameras"] = camdivider
                camdivider.properties["work_template"] = work_template

            # create a new item parented to the supplied session item. We
            # define an item type (maya.session.camera) that will be
            # used by an associated camera publish plugin as it searches for
            # items to act upon. We also give the item a display type and
            # display name. In the future, other publish plugins might attach to
            # these camera items to perform other actions
            cam_item = item_types["cameras"].create_item(
                "maya.session.camera", "Camera", camera_name
            )

            # set the icon for the item
            cam_item.set_icon_from_path(icon_path)

            # store the camera name so that any attached plugin knows which
            # camera this item represents!
            cam_item.properties["work_template"] = work_template
            cam_item.properties["camera_name"] = camera_name
            cam_item.properties["camera_shape"] = camera_shape
            cam_item.properties["publish_name"] = camera_name + '_' + self.parent.context.step["name"]


    def _collect_object_geo(self, parent_item, item_types, work_template):
        """
        Creates items for each abc set in the scene.

        :param parent_item: The maya session parent item
        """

        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "geometry.png")
        search = "geo"
        namespaceSearch = ":geo"

        for object_geo in cmds.ls(assemblies=True):
            if cmds.listRelatives(object_geo, ad=True, fullPath=True):
                for node in cmds.listRelatives(object_geo, ad=True, fullPath=True):
                    nombre = node.split("|")[-1]
                    if search == nombre or namespaceSearch in nombre:
                        try:
                            nodeName = str(cmds.listRelatives(node, p=True)[0]).replace(":", "_")
                        except:
                            nodeName = str(cmds.listRelatives(node, p=True)[0])

                        if "geometries" not in item_types:
                            geodivider = parent_item.create_item("maya.session.geometries", "Geometries",
                                                              "All Session Geometries")
                            geodivider.set_icon_from_path(icon_path)
                            geodivider.expanded = False
                            item_types["geometries"] = geodivider
                            geodivider.properties["work_template"] = work_template
                            geodivider.properties["object_name"] = "Session"

                        if "geometries_object" not in item_types:
                            geometries_object = item_types["geometries"].create_item("maya.session.geometries.objects", "Geometries",
                                                                 "Objects")
                            geometries_object.set_icon_from_path(icon_path)
                            item_types["geometries_object"] = geometries_object
                            geometries_object.expanded = False


                        geo_object_item = item_types["geometries_object"].create_item(
                            "maya.session.object_geo", "Object Geometry", nodeName
                        )

                        # set the icon for the item
                        geo_object_item.set_icon_from_path(icon_path)


                        # store the selection set name so that any attached plugin knows which
                        # selection set this item represents!
                        geo_object_item.properties["work_template"] = work_template
                        geo_object_item.properties["object_name"] = nodeName
                        geo_object_item.properties["object"] = node

    def _collect_object_geo_group(self, parent_item, item_types, work_template):
        """
        Creates items for each abc set in the scene.

        :param parent_item: The maya session parent item
        """

        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "geometry.png")

        search = "_geoGroup"

        for object_geo in cmds.ls(assemblies=True):
            if cmds.listRelatives(object_geo, ad=True, fullPath=True):
                for node in cmds.listRelatives(object_geo, ad=True, fullPath=True):
                    nombre = str(cmds.ls(node, long = False)[0]).split("|")[-1]
                    if search in nombre:

                        if "geometries" not in item_types:
                            geodivider = parent_item.create_item("maya.session.geometries", "Geometries",
                                                              "All Session Geometries")
                            geodivider.set_icon_from_path(icon_path)
                            geodivider.expanded = False
                            item_types["geometries"] = geodivider
                            geodivider.properties["work_template"] = work_template
                            geodivider.properties["object_name"] = "Session"


                        if "geometries_group" not in item_types:
                            geometries_group = item_types["geometries"].create_item("maya.session.geometries.groups", "Geometry Groups",
                                                                 "Geo Groups")
                            geometries_group.set_icon_from_path(icon_path)
                            item_types["geometries_group"] = geometries_group
                            geometries_group.expanded = False

                        geo_group_object_item = item_types["geometries_group"].create_item(
                            "maya.session.object_geo_group", "Object Geometry Group", nombre
                        )

                        # set the icon for the item
                        geo_group_object_item.set_icon_from_path(icon_path)


                        # store the selection set name so that any attached plugin knows which
                        # selection set this item represents!
                        geo_group_object_item.properties["work_template"] = work_template
                        geo_group_object_item.properties["object_name"] = nombre
                        geo_group_object_item.properties["object"] = node


    # def _collect_object_sets(self, parent_item, item_types, work_template):
    #     """
    #     Creates items for each set in the scene.
    #
    #     :param parent_item: The maya session parent item
    #     """
    #
    #     icon_path = os.path.join(self.disk_location, os.pardir, "icons", "geometry.png")
    #
    #
    #     for set in cmds.ls(type='quickSelectSet'):
    #         if "geometries" not in item_types:
    #             geodivider = parent_item.create_item("maya.session.geometries", "Geometries",
    #                                               "All Session Geometries")
    #             geodivider.set_icon_from_path(icon_path)
    #             geodivider.expanded = False
    #             item_types["geometries"] = geodivider
    #             geodivider.properties["work_template"] = work_template
    #             geodivider.properties["object_name"] = "Session"
    #
    #
    #         if "sets" not in item_types:
    #             geometries_set = item_types["geometries"].create_item("maya.session.geometries.set", "Geometry SETS",
    #                                                  "SETS")
    #             geometries_set.set_icon_from_path(icon_path)
    #             item_types["sets"] = geometries_set
    #             geometries_set.expanded = False
    #
    #         geo_set_object_item = item_types["sets"].create_item(
    #             "maya.session.object_geo_set", "Object Geometry Set", nombre
    #         )
    #
    #         # set the icon for the item
    #         geo_set_object_item.set_icon_from_path(icon_path)
    #
    #
    #         # store the selection set name so that any attached plugin knows which
    #         # selection set this item represents!
    #         geo_set_object_item.properties["work_template"] = work_template
    #         geo_set_object_item.properties["object_name"] = set
    #         geo_set_object_item.properties["object"] = set


    def _collect_particles_geo(self, parent_item, item_types, work_template):
        """
        Creates items for each particles node in the scene.

        :param parent_item: The maya session parent item
        """

        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "particles.png")

        for particles_geo in cmds.ls(type="nParticle"):

            nodeExport = particles_geo
            nodeName = particles_geo

            if "fx" not in item_types:
                fxdivider = parent_item.create_item("maya.session.fx", "FX",
                                                        "All Session FX")
                fxdivider.set_icon_from_path(icon_path)
                fxdivider.expanded = False
                item_types["fx"] = fxdivider
                fxdivider.properties["work_template"] = work_template
            particles_object_item = item_types["fx"].create_item(
                "maya.session.particles_geo", "Particles Cache", nodeName
            )

            particles_object_item.set_icon_from_path(icon_path)



            # store the selection set name so that any attached plugin knows which
            # selection set this item represents!
            particles_object_item.properties["object_name"] = nodeName
            particles_object_item.properties["object"] = nodeExport

    def _collect_ass(self, parent_item, item_types, work_template):
        """
        Creates items for each standin node in the scene.

        :param parent_item: The maya session parent item
        """

        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "particles.png")

        for ass in cmds.ls(type="aiStandIn"):

            nodeExport = ass
            nodeName = ass

            if "fx" not in item_types:
                fxdivider = parent_item.create_item("maya.session.fx", "FX",
                                                        "All Session FX")
                fxdivider.set_icon_from_path(icon_path)
                fxdivider.expanded = False
                item_types["fx"] = fxdivider
                fxdivider.properties["work_template"] = work_template


            ass_object_item = item_types["fx"].create_item(
                "maya.session.ass", "Ass Cache", nodeName
            )

            ass_object_item.set_icon_from_path(icon_path)



            # store the selection set name so that any attached plugin knows which
            # selection set this item represents!
            ass_object_item.properties["object_name"] = nodeName
            ass_object_item.properties["object"] = nodeExport

    def _collect_vdb(self, parent_item, item_types, work_template):
        """
        Creates items for each Volume node in the scene.

        :param parent_item: The maya session parent item
        """

        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "particles.png")

        search = "vdb"

        for volume in cmds.ls(type="aiVolume"):

            if volume == search:
                nodeExport = volume
                nodeName = volume

                if "fx" not in item_types:
                    fxdivider = parent_item.create_item("maya.session.fx", "FX",
                                                        "All Session FX")
                    fxdivider.set_icon_from_path(icon_path)
                    fxdivider.expanded = False
                    item_types["fx"] = fxdivider
                    fxdivider.properties["work_template"] = work_template

                vdb_object_item = item_types["fx"].create_item(
                    "maya.session.vdb", "Volume VDB", nodeName
                )

                vdb_object_item.set_icon_from_path(icon_path)



                # store the selection set name so that any attached plugin knows which
                # selection set this item represents!
                vdb_object_item.properties["object_name"] = nodeName
                vdb_object_item.properties["object"] = nodeExport

    def _cam_name_matches_settings(self, camera_name, settings):
        """
        Returns True if the supplied camera name matches any of the configured
        camera name patterns.
        """

        # loop through each pattern specified and see if the supplied camera
        # name matches the pattern
        cam_patterns = settings["Cameras"].value

        # if no patterns specified, then no constraints on camera name
        if not cam_patterns:
            return True

        for camera_pattern in cam_patterns:
            if fnmatch.fnmatch(camera_name, camera_pattern):
                return True

        return False
def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = cmds.file(query=True, sn=True)

    if path is not None:
        path = six.ensure_str(path)

    return path


