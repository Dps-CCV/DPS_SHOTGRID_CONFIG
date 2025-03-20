import nuke
import os


class FormatFixing:
    def fix(self):
        print("aquí")
        writeNode = nuke.thisNode()
        group = ''.join(nuke.thisNode().fullName().split('.')[:-1])
        groupNode = nuke.toNode(group)
        if groupNode.knob("profile_name").getValue() in ['PRECOMP', 'TECH_PRECOMP', 'Render 16bits', 'IMAGE_PLANE', 'ALPHA']:
            print("hilllo")
            print(groupNode.knobs())
            print(groupNode.knob("_promoted_0").getValue())
            print(groupNode["_promoted_0"].value())
            print(groupNode.knob("tk_file_type").getValue())
            print(groupNode.knob("profile_name").getValue())
            #for key, value in groupNode.knobs().items():
            #    print("key " + key)
            #    print("value " + str(groupNode.knob(key).getValue()))
            texto = groupNode.knob("tk_file_type_settings").getValue()
            indice = texto.find("Vcompression")+17
            nuevotexto = texto[indice:]
            nuevoindice = nuevotexto.find("\n")
            compr = nuevotexto[:nuevoindice]
            print(compr)
            writeNode.knob("file_type").setValue(groupNode.knob("tk_file_type").getValue())
            writeNode.knob("compression").setValue(compr)