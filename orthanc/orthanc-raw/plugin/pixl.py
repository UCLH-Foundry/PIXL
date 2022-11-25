#  Copyright (c) 2022 University College London Hospitals NHS Foundation Trust
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import orthanc

def OnChange(changeType, level, resourceId):
    # Taken from: 
    # https://book.orthanc-server.com/plugins/python.html#auto-routing-studies
    if changeType == orthanc.ChangeType.STABLE_STUDY:
        print('Stable study: %s' % resourceId)
        orthanc.RestApiPost('/modalities/PIXL-Anon/store', resourceId)

def OnHeartBeat(output, uri, **request):
    orthanc.LogWarning("OK")
    output.AnswerBuffer('OK\n', 'text/plain')

orthanc.RegisterOnChangeCallback(OnChange)
orthanc.RegisterRestCallback('/heart-beat', OnHeartBeat)