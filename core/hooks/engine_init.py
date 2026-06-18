# Copyright (c) 2018 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Hook that gets executed every time an engine has been fully initialized.
"""

from tank import Hook


class EngineInit(Hook):
    def execute(self, engine, **kwargs):
        """
        Executed when a Toolkit engine has been fully initialized.

        At this point, all apps and frameworks have been loaded,
        and the engine is fully operational.

        The default implementation does nothing.

        :param engine: Engine that has been initialized.
        :type engine: :class:`~sgtk.platform.Engine`
        """
        ##synchronize path cache
        if engine.context.project:
            self.logger.info("Synchronize folders")
            try:
                tk = engine.sgtk
                tk.synchronize_filesystem_structure(full_sync=True)
                self.logger.info("Sync done")
            except Exception as e:
                self.logger.info("Synchronize folders failed")
                self.logger.info(e)


        if engine.name == "tk-maya":
            import maya.cmds as cmds
            import sgtk
            def SetResolution(self):
                engine = sgtk.platform.current_engine()
                sg = engine.shotgun
                context = engine.context.entity
                shot = sg.find_one(context['type'], [['id', 'is', context['id']]], ['sg_width', 'sg_height'])
                if shot['sg_width'] != None:
                    pAx = cmds.getAttr("defaultResolution.pixelAspect")
                    pAr = cmds.getAttr("defaultResolution.deviceAspectRatio")
                    cmds.setAttr("defaultResolution.aspectLock", 0)
                    cmds.setAttr("defaultResolution.width", shot['sg_width'])
                    cmds.setAttr("defaultResolution.height", shot['sg_height'])
                    cmds.setAttr("defaultResolution.pixelAspect", pAx)
                    cmds.setAttr("defaultResolution.deviceAspectRatio", pAr)
                    cmds.setAttr("defaultResolution.aspectLock", 1)
                    texto = "Render settings resolution changed to: " + str(shot['sg_width']) + "x" + str(shot['sg_height'])
                    cmds.confirmDialog(title="Resolution Mismatch", message=texto)

            # first, set up our callback, calling out to a method inside the app module contained
            # in the python folder of the app
            menu_callback = lambda: SetResolution(self)

            # now register the command with the engine
            engine.register_command("Set Shot Resolution", menu_callback)

        elif engine.name == 'tk-nuke':
            import nuke
            try:
                ####DPS Write Shortcuts
                # # CUSTOM SHORTCUTS
                write_node_item = nuke.menu('Nodes').findItem("Image/Write")
                write_node_item.setShortcut("")

                nuke.menu('Nodes').findItem("Flow Production Tracking").findItem(
                    "Render 16bits").setShortcut('w')
                nuke.menu('Nodes').findItem("Flow Production Tracking").findItem(
                    "PRECOMP").setShortcut('Alt+w')
                nuke.menu('Nodes').findItem("Flow Production Tracking").findItem(
                    "TECH_PRECOMP").setShortcut('Alt+j')
            except:
                self.logger.info("No se ha podido registrar los atajos de nuke write")
        pass