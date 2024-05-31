def main():
  import shotgun-api3
  import os
  sg = shotgun_api3.Shotgun("https://dareplanet.shotgunbstudio.com",
                          script_name="GithubUpdateConfig",
                          api_key=os.environ['UPDATECONFIGKEY'])
  data = {'descriptor': "sgtk:descriptor:git_branch?branch=master&path=https://github.com/Dps-CCV/DPS_SHOTGRID_CONFIG.git&version="+os.environ['NEWCODE']}
  sg.update('PipelineConfiguration', 2215, data)



if __name__ == '__main__':
  main()
