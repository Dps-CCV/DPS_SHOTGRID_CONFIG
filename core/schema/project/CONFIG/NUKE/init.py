import nuke
import os

# Add Nuke pipeline paths
additionalPaths = [
    './SCRIPTS',
    './TEMPLATES',
    './SET',
    './ICONS',
    './SCRIPTS/rvnuke'
]


for p in additionalPaths:
    nuke.pluginAddPath(p)


import copy_rendered_files
import RenderVersionsLimit
import RenderChecks_WriteTank


nuke.knobDefault('Root.colorManagement', 'OCIO')
nuke.knobDefault("Viewer.viewerProcess", 'Rec.709 (ACES)')
projectColorspace = os.environ['PROJECTCOLORSPACE']
nuke.knobDefault('Root.floatLut', projectColorspace)
nuke.knobDefault('Root.workingSpaceLUT', 'ACEScg')
nuke.knobDefault('Root.int8Lut', 'sRGB - Texture')
nuke.knobDefault('Root.int16Lut', 'ACEScct')
nuke.knobDefault('Root.logLut', 'ACEScct')
nuke.knobDefault('Root.monitorLut', 'ACES 1.0 - SDR Video (Rec.1886 Rec.709 - Display)')
nuke.knobDefault('Root.monitorOutLUT', 'ACES 1.0 - SDR Video (Rec.1886 Rec.709 - Display)')
nuke.knobDefault("Viewer.freezeGuiWhenPlayBack", "1")
nuke.knobDefault("Viewer.viewerProcess", 'ACES 1.0 - SDR Video (Rec.1886 Rec.709 - Display)')









