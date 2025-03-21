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
Hook that gets executed every time a new PipelineConfiguration instance is created.
"""

from tank import Hook
import tank
import os


class PipelineConfigurationInit(Hook):
    def execute(self, **kwargs):
        """
        Executed when a new PipelineConfiguration instance is initialized.

        The default implementation does nothing.
        """
        index = __file__.find("core\\")
        config = __file__[:index]
        os.environ['CONFIG_FOLDER'] = config
        os.environ["FormExt"] = 'exr'
        os.environ["CompressionExt"] = 'none'

        pass
