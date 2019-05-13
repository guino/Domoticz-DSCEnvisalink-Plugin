#           DSC/Honeywell EnvisaLink 3 & 4 Alarm interface Plugin
#
#           Author:     Dnpwwo & Wagner Oliveira, 2019
#
"""
<plugin key="EnvisaLink" name="DSC/Honeywell Alarm via EnvisaLink" author="dnpwwo & Wagner Oliveira" version="3.0" wikilink="https://github.com/guino/Domoticz-DSCEnvisalink-Plugin" externallink="http://www.eyezon.com/?page_id=176">
    <description>
        <h2>EnvisaLink 3 & 4 Alarm interface for DSC/Honeywell Alarms</h2><br/>
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>Shows Zone and Partition status in Domoticz</li>
            <li>Can be integrated with the Domoticz Security Panel to allow Arm & Disarm operations from Domoticz</li>
            <li>Bypassed Zones shown with Red banner in Domoticz *DSC ONLY</li>
        </ul>
        <h3>Devices</h3>
        <ul style="list-style-type:square">
            <li>Zones - Contact device per zone that show Open/Closed status.  These can be changed to 'Motion' devices in the Device Edit page and they will show On/Off (recommend setting an Off Delay otherwise activity is rarely seen in the Web UI)</li>
            <li>Partition - Alert per partition that shows partition state, useful if you don't want to use the Security Panel integration or you have more than one partition.</li>
            <li>Command Output - Contact device for each Command Output/Partition combination seen. The DSC only reports activation so an Off Delay must exist for the device to reset) *DSC ONLY</li>
            <li>Security Panel - Optionally creates a Security Panel device that allows arming and disarming via Domoticz.</li>
            <li>Alarm Selector - Device that allows arming and disarming via Domoticz. *HONEYWELL ONLY</li>
        </ul>
    </description>
    <params>
        <param field="Address" label="IP Address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="30px" required="true" default="4025"/>
        <param field="Password" label="Envisalink Password" width="200px" required="true" default="" password="true"/>
        <param field="Mode1" label="Max. Partitions" width="50px">
            <options>
                <option label="1" value="1" default="true"/>
                <option label="2" value="2" />
            </options>
        </param>
        <param field="Mode2" label="Max. Zones" width="50px">
            <options>
                <option label="1" value="1"/>
                <option label="2" value="2" />
                <option label="3" value="3" />
                <option label="4" value="4" />
                <option label="5" value="5" />
                <option label="6" value="6" default="true"/>
                <option label="7" value="7" />
                <option label="8" value="8" />
                <option label="9" value="9" />
                <option label="10" value="10" />
                <option label="11" value="11" />
                <option label="12" value="12" />
                <option label="13" value="13" />
                <option label="14" value="14" />
                <option label="15" value="15" />
                <option label="16" value="16"/>
                <option label="17" value="17" />
                <option label="18" value="18" />
                <option label="19" value="19" />
                <option label="20" value="20"/>
                <option label="64" value="64" />
            </options>
        </param>
        <param field="Mode3" label="Integrated Security Panel" width="75px">
            <options>
                <option label="True" value="True" default="True"/>
                <option label="False" value="False" />
            </options>
        </param>
        <param field="Mode4" label="Alarm Passcode" width="75px" default="" password="true" />
        <param field="Mode5" label="Time Out Lost Devices" width="75px">
            <options>
                <option label="True" value="True" default="True"/>
                <option label="False" value="False" />
            </options>
        </param>
        <param field="Mode6" label="Debug" width="150px">
            <options>
                <option label="None" value="0"  default="true" />
                <option label="Python Only" value="2"/>
                <option label="Basic Debugging" value="62"/>
                <option label="Basic+Messages" value="126"/>
                <option label="Connections Only" value="16"/>
                <option label="Connections+Python" value="18" default="true" />
                <option label="Connections+Queue" value="144"/>
                <option label="All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
from dsc_envisalinkdefs import *
from alarm_state import AlarmState
from datetime import datetime
from time import time
import sys
import re
import json

ZONE_BASE = 0
SECURITY_PANEL = 100
PARTITION_BASE = 100  # First partition will be this + partition number so 101
OUTPUT_BASE = 100     # Device will be number will be this + 10*partition + output. i.e partition 1 output 2 = Device 112
ARMIDX = 103
ACIDX = 104
CHIMEIDX = 105

class BasePlugin:
    alarmConn = None
    alarmState = None
    nextConnect = 3
    heartbeatInterval = 20
    nextTimeSync = 0
    oustandingPings = 0
    HWTYPE=0

    def onStart(self):
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()

        self.alarmState = AlarmState.get_initial_alarm_state(int(Parameters["Mode2"]), int(Parameters["Mode1"]))

        self.alarmConn = Domoticz.Connection(Name="EnvisaLink", Transport="TCP/IP", Protocol="Line", Address=Parameters["Address"], Port=Parameters["Port"])
        self.alarmConn.Connect()

        Domoticz.Heartbeat(self.heartbeatInterval)

    def onConnect(self, Connection, Status, Description):
        if (Status == 0):
            Domoticz.Log("Connected successfully to: "+Connection.Address+":"+Connection.Port)
            self.nextTimeSync = 0
        else:
            Domoticz.Log("Failed to connect ("+str(Status)+") to: "+Connection.Address+":"+Connection.Port)
            for Key in Devices:
                UpdateDevice(Key, 0, Devices[Key].sValue, 1)

    def onMessage(self, Connection, Data):
        global evl_ResponseTypes
        strData = Data.decode("utf-8", "ignore").strip()

        if (ValidChecksum(strData)):
            dataoffset = 0
            if re.match('\d\d:\d\d:\d\d\s', strData):
                dataoffset = dataoffset + 9
            code = strData[dataoffset:dataoffset+3]
            data = strData[dataoffset+3:][:-2]

            if code in evl_ResponseTypes:
                try:
                    handlerFunc = getattr(self, "handle_"+evl_ResponseTypes[code]['handler'], self.notHandled)
                    result = handlerFunc(code, data)
                    self.updateDomoticz()
                except AttributeError:
                    Domoticz.Error(str.format("No handler exists for code: {0}. Skipping.", evl_ResponseTypes[code]['handler']))
                except KeyError as err:
                    Domoticz.Error("No handler configured for '"+str(code)+"' code.")
                except TypeError as e:
                    Domoticz.Error("Type error: {0}".format(e))
            else:
                self.notHandled(code, data)
        else:
            # Message doesn't have valid DSC protocol checksum, so check if it matches Honeywell login
            if str(strData) == "Login:":
                self.HWTYPE = 1
                Domoticz.Log("Honeywell System Detected! Sending Login...")
                message = Parameters["Password"]+"\r\n"
                self.alarmConn.Send(message)
            # If it's Honeywell hardware forward messages to its handler
            elif self.HWTYPE == 1:
                self.handle_honeywell(str(strData))
            else:
                Domoticz.Error("EnvisaLink returned invalid message: '"+str(strData)+"'. Checksums: Calculated "+str(checkSum)+" and Original "+str(int(origChecksum,16)))

    def handle_honeywell(self, data):
        # If Login OK response
        if data == "OK":
            Domoticz.Log("Honeywell Login OK!")
            if (not ACIDX in Devices):
                Domoticz.Device(Name="AC Power", Unit=ACIDX, Type=244, Subtype=73, Switchtype=0, Image=9).Create()
            if (not CHIMEIDX in Devices):
                Domoticz.Device(Name="Chime", Unit=CHIMEIDX, Type=244, Subtype=73, Switchtype=0, Image=8).Create()
            if (not ARMIDX in Devices):
                Options = {"LevelActions": "||||", "LevelNames": "Disarm|Arm Away|Arm Stay|Arm Away Zero Delay|Arm Stay Zero Delay", \
                    "LevelOffHidden": "false", "SelectorStyle": "1"}
                Domoticz.Device(Name="Arm Mode", Unit=ARMIDX, TypeName="Selector Switch", Options=Options, Image=13).Create()
            # Request zone timer dump (to detect/add zones as devices)
            self.alarmConn.Send("^02,$\r\n")
            # Request status
            self.alarmConn.Send("*\r\n")
        # If Login FAILED response
        elif data == "FAILED":
            Domoticz.Log("Honeywell Login FAILED!")
            # Nothing to do
        # If it's a data update message
        elif data.startswith('%'):
            Domoticz.Log("Honeywell Data message: "+data)
            # If it's zone timer dump
            if data.startswith('%FF'):
                self.handle_hwzonedump(data)
            # If it's a generic status update (sent at least every 10s)
            elif data.startswith('%00'):
                self.handle_hwstatus(data)
            # If it's a zone status update
            elif data.startswith('%01'):
                self.handle_hwzoneupdate(data)
            # If it's a partition status update
            elif data.startswith('%02'):
                self.handle_hwpartupdate(data)
            # Something else we don't know about
            else:
                Domoticz.Log("Honeywell unhandled data: "+data)
        else:
            Domoticz.Log("Honeywell unhandled data: "+data)

    def handle_hwstatus(self, data):
        # Get partition for status update
        part = int(data[4:6])

        # Get overall status
        status = int(data[7:11], 16)

        # check armed status
        if status & 0x8000 > 0:
            # armed stay (3=with zero delay)
            self.alarmState['partition'][part]['status'].update(evl_ArmModes['3' if status & 0x80 > 0 else '1']['status'])
        elif status & 0x4 > 0:
            # armed away (2=with zero delay)
            self.alarmState['partition'][part]['status'].update(evl_ArmModes['2' if status & 0x80 > 0 else '0']['status'])
        else:
            # disarmed, but is it 'ready' or not
            if status & 0x1000 > 0:
                # Ready
                self.alarmState['partition'][part]['status'].update(evl_ResponseTypes['650']['status'])
                # zones bypassed ?
                if status & 0x80 > 0:
                    self.alarmState['partition'][part]['status']['alpha'] = "Ready with zones bypassed"
            else:
                # Not ready
                self.alarmState['partition'][part]['status'].update(evl_ResponseTypes['651']['status'])
                # Read zone number and mark it as open and save last fault time
                zone = int(data[12:14])
                self.alarmState['zone'][zone]['partition'] = part
                self.alarmState['zone'][zone]['last_fault'] = time()
                self.alarmState['zone'][zone]['status']['open'] = True
                # If we don't have a device for it
                if (not ZONE_BASE+zone in Devices):
                    Domoticz.Device(Name="Zone "+str(ZONE_BASE+zone), Unit=ZONE_BASE+zone, Type=244, Subtype=73, Switchtype=11).Create()
                # Make sure device has initial state
                UpdateDevice(ZONE_BASE+zone, 1, 'Open', self.alarmState['zone'][zone]['status']['bypass'])

        # Get AC status
        if status & 0x8:
            self.alarmState['partition'][part]['status']['ac_present'] = True
            UpdateDevice(ACIDX, 1, "ON", False)
        else:
            self.alarmState['partition'][part]['status']['ac_present'] = False
            UpdateDevice(ACIDX, 0, "OFF", False)

        # Get Chime status
        if status & 0x20:
            self.alarmState['partition'][part]['status']['chime'] = True
            UpdateDevice(CHIMEIDX, 1, "ON", False)
        else:
            self.alarmState['partition'][part]['status']['chime'] = False
            UpdateDevice(CHIMEIDX, 0, "OFF", False)

        self.updateDomoticz()

    def handle_hwzoneupdate(self, data):
        for zone in self.alarmState['zone']:
            pos = 4+((zone//8)*2)
            bit = int(data[pos:pos+2], 16) & (1<<((zone-1) % 8))
            if bit > 0:
                self.alarmState['zone'][zone]['last_fault'] = time()
                self.alarmState['zone'][zone]['status']['open'] = True
                # If we don't have a device for it
                if (not ZONE_BASE+zone in Devices):
                    Domoticz.Device(Name="Zone "+str(ZONE_BASE+zone), Unit=ZONE_BASE+zone, Type=244, Subtype=73, Switchtype=11).Create()
            else:
                self.alarmState['zone'][zone]['status']['open'] = False
            # Update device status
            UpdateDevice(ZONE_BASE+zone, 1 if self.alarmState['zone'][zone]['status']['open'] else 0, \
                        'Closed' if bit == 0 else 'Open', \
                        self.alarmState['zone'][zone]['status']['bypass'])

    def handle_hwpartupdate(self, data):
        for part in self.alarmState['partition']:
            status = int(data[(2+2*part):(4+2*part)])
            Domoticz.Log("partupdate "+str(part)+" status="+str(status)+" / "+data[(2+2*part):(4+2*part)])

            # Set this to false (only set to true in status 9)
            self.alarmState['partition'][part]['status']['alarm_in_memory'] = False;

            # Ready
            if status == 1 or status == 2:
                self.alarmState['partition'][part]['status'].update(evl_ResponseTypes['650']['status'])
                if status == 2:
                    self.alarmState['partition'][part]['status']['alpha'] = "Ready with zones bypassed"

            # Not Ready
            elif status == 3:
                self.alarmState['partition'][part]['status'].update(evl_ResponseTypes['651']['status'])

            # Armed STAY
            elif status == 4:
                self.alarmState['partition'][part]['status'].update(evl_ArmModes['1']['status'])

            # Armed AWAY
            elif status == 5:
                self.alarmState['partition'][part]['status'].update(evl_ArmModes['0']['status'])

            # Armed STAY Zero Delay
            elif status == 6:
                self.alarmState['partition'][part]['status'].update(evl_ArmModes['3']['status'])

            # Exit Delay
            elif status == 7:
                self.alarmState['partition'][part]['status'].update(evl_ResponseTypes['656']['status'])

            # Alarm
            elif status == 8:
                self.alarmState['partition'][part]['status'].update(evl_ResponseTypes['654']['status'])

            # Ready with alarm in memory
            elif status == 9:
                self.alarmState['partition'][part]['status'].update(evl_ResponseTypes['650']['status'])
                self.alarmState['partition'][part]['status']['alpha'] = "Ready Alarm in Memory"
                self.alarmState['partition'][part]['status']['alarm_in_memory'] = True;

            # Armed AWAY Zero Delay
            elif status == 10:
                self.alarmState['partition'][part]['status'].update(evl_ArmModes['2']['status'])

            # If the partition is ready
            if self.alarmState['partition'][part]['status']['ready']:
                # For each zone we know to be in this partition set status to false
                for zone in self.alarmState['zone']:
                    if self.alarmState['zone'][zone]['partition'] == part:
                        self.alarmState['zone'][zone]['status']['open'] = False
                        UpdateDevice(ZONE_BASE+zone, 0, 'Closed', self.alarmState['zone'][zone]['status']['bypass'])

        self.updateDomoticz()

    def handle_hwzonedump(self, data):
        # Process timer from each zone
        for zone in self.alarmState['zone']:
            pos = 4 + (zone-1)*4;
            # If this zone has ever been seen
            if data[pos:pos+4] != "0000":
                # if it's not already added as device, add it
                if (not ZONE_BASE+zone in Devices):
                    Domoticz.Device(Name="Zone "+str(ZONE_BASE+zone), Unit=ZONE_BASE+zone, Type=244, Subtype=73, Switchtype=11).Create()
                # Read timer, set open if it's less than 60 seconds ago
                timer = (0xFFFF-int(str(data[pos+2:pos+4])+str(data[pos:pos+2]), 16))*5
                self.alarmState['zone'][zone]['last_fault'] = time()
                self.alarmState['zone'][zone]['status']['open'] = (timer < 60)
                Domoticz.Log("zone "+str(zone)+" timer="+str(timer)+" epoch="+str(time()))
                # Make sure device has initial state
                UpdateDevice(ZONE_BASE+zone, 1 if self.alarmState['zone'][zone]['status']['open'] else 0, \
                            'Closed' if timer > 60 else 'Open', \
                            self.alarmState['zone'][zone]['status']['bypass'])

        self.updateDomoticz()

    def onSecurityEvent(self, Unit, Level, Description):
        Domoticz.Status("onSecurityEvent called for Level " + str(Level) + ": Description '" + str(Description) + "', Connected: " + str(self.alarmConn.Connected()))
        # Multiple events can be passed for the same action, e.g during arming 1 event when requested, 1 event after exit timer counts to 0
        if (Level == 0):    # Disarm
            if ((self.alarmState['partition'][1]['status']['armed_stay'] == True) or (self.alarmState['partition'][1]['status']['armed_away'] == True)):
                Domoticz.Status("Requesting partition Disarm")
                if self.HWTYPE==1:
                    self.alarmConn.Send(Parameters['Mode4']+'1')
                else:
                    self.alarmConn.Send(CreateChecksum(evl_Commands['Disarm']+'1'+Parameters["Mode4"]))
        elif (Level == 1):  # Arm Stay
            if ((self.alarmState['partition'][1]['status']['armed_stay'] == False) and (self.alarmState['partition'][1]['status']['armed_away'] == False)):
                Domoticz.Status("Requesting partition Armed Stay")
                if self.HWTYPE==1:
                    self.alarmConn.Send(Parameters['Mode4']+'3')
                else:
                    self.alarmConn.Send(CreateChecksum(evl_Commands['ArmStay']+'1'))
        elif (Level == 2):  # Arm Away
            if ((self.alarmState['partition'][1]['status']['armed_stay'] == False) and (self.alarmState['partition'][1]['status']['armed_away'] == False)):
                Domoticz.Status("Requesting partition Armed Away")
                if self.HWTYPE==1:
                    self.alarmConn.Send(Parameters['Mode4']+'2')
                else:
                    self.alarmConn.Send(CreateChecksum(evl_Commands['ArmAway']+'1'))
        else:
            Domoticz.Error("Security Event contains unknown data: '"+str(Level)+"' with description: '"+Description+"'")

    def updateDomoticz(self):
        # Sync Devices to Alarm state
        for zone in self.alarmState['zone']:
            # For DSC Always check/add zones as devices, For Honeywell they're added on auto-detection (during zone timer dump)
            if self.HWTYPE == 0 and (not ZONE_BASE+zone in Devices):
                Domoticz.Device(Name="Zone "+str(ZONE_BASE+zone), Unit=ZONE_BASE+zone, Type=244, Subtype=73, Switchtype=2).Create()
            sValue = 'Closed'
            if self.alarmState['zone'][zone]['status']['open']:   sValue='Open'
            if self.alarmState['zone'][zone]['status']['bypass']: sValue='Bypass'
            if self.alarmState['zone'][zone]['status']['tamper']: sValue='Tamper'
            UpdateDevice(ZONE_BASE+zone, \
                        1 if self.alarmState['zone'][zone]['status']['open'] else 0, \
                        sValue, \
                        self.alarmState['zone'][zone]['status']['bypass'])

        for part in self.alarmState['partition']:
            if (not PARTITION_BASE+part in Devices):
                Domoticz.Device(Name="Partition "+str(part), Unit=PARTITION_BASE+part, TypeName='Alert').Create()
            nValue = 1 if self.alarmState['partition'][part]['status']['ready'] else 2
            if self.alarmState['partition'][part]['status']['trouble']: nValue=2
            if self.alarmState['partition'][part]['status']['alarm']:   nValue=3
            UpdateDevice(PARTITION_BASE+part, nValue, \
                        self.alarmState['partition'][part]['status']['alpha'], \
                        self.alarmState['partition'][part]['status']['trouble'])

        if Parameters["Mode3"] != "False":
            if (not SECURITY_PANEL in Devices):
                #Domoticz.Device(Name="Security Panel", Unit=SECURITY_PANEL, TypeName="Security Panel").Create()
                Domoticz.Device(Name="Security Panel", Unit=SECURITY_PANEL, Type=32, Subtype=131).Create()
                Domoticz.Log("Created Domoticz integrated Security Panel device for partition 1.")
            nValue=0    # sStatusNormal
            if self.alarmState['partition'][1]['status']['alarm']:        nValue=2              # sStatusAlarm
            if self.alarmState['partition'][1]['status']['armed_away']:   nValue=9              # sStatusArmAway
            if self.alarmState['partition'][1]['status']['armed_stay']:   nValue=11             # sStatusArmHome
            if self.alarmState['partition'][1]['status']['trouble']:      nValue=nValue+128     # sStatusNormalTamper or sStatusAlarmTamper
            UpdateDevice(SECURITY_PANEL, nValue, "", self.alarmState['partition'][1]['status']['trouble'])

        if self.HWTYPE == 1:
            sText = '0'
            if self.alarmState['partition'][1]['status']['armed_zero_entry_delay']:
                if self.alarmState['partition'][1]['status']['armed_away']: sText='30'
                if self.alarmState['partition'][1]['status']['armed_stay']: sText='40'
            else:
                if self.alarmState['partition'][1]['status']['armed_away']: sText='10'
                if self.alarmState['partition'][1]['status']['armed_stay']: sText='20'
            UpdateDevice(ARMIDX, 2, sText, self.alarmState['partition'][1]['status']['trouble'])

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level) + ", Connected: " + str(self.alarmConn.Connected()))
        Command = Command.strip()
        action, sep, params = Command.partition(' ')
        action = action.capitalize()
        # If Chime
        if Unit == CHIMEIDX:
            # Toggle it
            self.alarmConn.Send(Parameters['Mode4']+'9')
            # Request status
            self.alarmConn.Send('*')
        if Unit == ARMIDX:
            # If already armed, disarm first
            if self.alarmState['partition'][1]['status']['armed_away'] or self.alarmState['partition'][1]['status']['armed_stay']:
                self.alarmConn.Send(Parameters['Mode4']+'1')

            # Arm Away
            if Level == 10:
                self.alarmConn.Send(Parameters['Mode4']+'2')
            # Arm Stay
            elif Level == 20:
                self.alarmConn.Send(Parameters['Mode4']+'3')
            # Arm Away Zero Delay (Not available on ADT Safewatch pro 3000)
            elif Level == 30:
                self.alarmConn.Send(Parameters['Mode4']+'4')
            # Arm Stay Zero Delay
            elif Level == 40:
                self.alarmConn.Send(Parameters['Mode4']+'7')

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Log("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onHeartbeat(self):
        if self.HWTYPE == 1:
            return self.alarmConn.Connected()
        try:
            if (self.alarmConn.Connected()):
                if (self.nextTimeSync <= 0):
                    now = datetime.now()
                    message = '{:02}{:02}{:02}{:02}{:02}'.format(now.hour, now.minute, now.month, now.day, now.year-2000)
                    Domoticz.Log("Sending time synchronization command ('"+message+"')")
                    self.alarmConn.Send(CreateChecksum(evl_Commands['TimeSync']+message))
                    self.nextTimeSync = int(3600/self.heartbeatInterval)  # sync time hourly
                else:
                    if (self.oustandingPings <= 0):
                        self.oustandingPings = int(300/self.heartbeatInterval)  # heartbeat every 5 minutes
                        self.alarmConn.Send(CreateChecksum(evl_Commands['KeepAlive']))
                self.nextTimeSync = self.nextTimeSync - 1
                self.oustandingPings = self.oustandingPings - 1
            elif (self.alarmConn.Connecting() != True):
                Domoticz.Log("Alarm not connected, requesting re-connect.")
                self.alarmConn.Connect()
            return True
        except:
            Domoticz.Log("Unhandled exception in onHeartbeat, forcing disconnect.")
            self.alarmConn.Disconnect()

    def onDisconnect(self, Connection):
        Domoticz.Log("Device has disconnected")
        if Parameters["Mode5"] != "False":
            for Device in Devices:
                UpdateDevice(Device, Devices[Device].nValue, Devices[Device].sValue, 1)
        return

    def onStop(self):
        Domoticz.Log("onStop called")
        return True

    def handle_zone_state_change(self, code, data):
        """Event 601-610."""
        parse = re.match('^[0-9]{3,4}$', data)
        if parse:
            zoneNumber = int(data[-3:])
            if (zoneNumber <= int(Parameters["Mode2"])):
                self.alarmState['zone'][zoneNumber]['status'].update(evl_ResponseTypes[code]['status'])
                Domoticz.Debug(str.format("[zone {0}] state has updated: {1}", zoneNumber, json.dumps(evl_ResponseTypes[code]['status'])))
            else:
                Domoticz.Debug(str.format("[zone {0}] state change ignored, invalid zone number.", zoneNumber))
            return zoneNumber
        else:
            Domoticz.Error("Invalid data ("+data+") has been passed in the zone update.")

    def handle_zone_timer_dump(self, code, data):
        parse = re.match('^[0-9A-F]{2}$', data)
        try:
            Domoticz.Debug(str.format("Message: '{0}' with data: {1}", evl_ResponseTypes[code]['name'], data))
        except:
            Domoticz.Error("zone_timer_dump error: '"+code+"' command, data: "+data)

    def handle_zone_bypass_update(self, code, data):
        """Event 616, Bypassed Zones Bit field Dump."""
        parse = re.match('^[0-9A-F]{2}$', data)
        Domoticz.Debug(str.format("Message: '{0}' with data: {1}", evl_ResponseTypes[code]['name'], data))
        allBypasses = [data[i:i+2] for i in range(0, len(data), 2)]
        zoneOffset = 0
        maxZone = int(Parameters["Mode2"])
        for bypasses in allBypasses:
            mask = int(bypasses,16)
            if (zoneOffset+1 <= maxZone): self.alarmState['zone'][zoneOffset+1]['status'].update({'bypass' : (mask & 1) > 0})
            if (zoneOffset+2 <= maxZone): self.alarmState['zone'][zoneOffset+2]['status'].update({'bypass' : (mask & 2) > 0})
            if (zoneOffset+3 <= maxZone): self.alarmState['zone'][zoneOffset+3]['status'].update({'bypass' : (mask & 4) > 0})
            if (zoneOffset+4 <= maxZone): self.alarmState['zone'][zoneOffset+4]['status'].update({'bypass' : (mask & 8) > 0})
            if (zoneOffset+5 <= maxZone): self.alarmState['zone'][zoneOffset+5]['status'].update({'bypass' : (mask & 16) > 0})
            if (zoneOffset+6 <= maxZone): self.alarmState['zone'][zoneOffset+6]['status'].update({'bypass' : (mask & 32) > 0})
            if (zoneOffset+7 <= maxZone): self.alarmState['zone'][zoneOffset+7]['status'].update({'bypass' : (mask & 64) > 0})
            if (zoneOffset+8 <= maxZone): self.alarmState['zone'][zoneOffset+8]['status'].update({'bypass' : (mask & 128) > 0})
            zoneOffset = zoneOffset + 8
            if (zoneOffset > maxZone): break

    def handle_partition_state_change(self, code, data):
        """Event 650-674, 652 is an exception, because 2 bytes are passed for partition and zone type."""
        partitionNumber = int(data[0])
        if (partitionNumber <= int(Parameters["Mode1"])):
            if code == '652':
                parse = re.match('^[0-9]{2}$', data)
                if parse:
                    self.alarmState['partition'][partitionNumber]['status'].update(evl_ArmModes[data[1]]['status'])
                    Domoticz.Debug(str.format("[partition {0}] state has updated: {1}", partitionNumber, json.dumps(evl_ArmModes[data[1]]['status'])))
                    return partitionNumber
                else:
                    Domoticz.Error("Invalid data ("+data+") has been passed when arming the alarm.")
            else:
                parse = re.match('^[0-9]+$', data)
                if parse:
                    self.alarmState['partition'][partitionNumber]['status'].update(evl_ResponseTypes[code]['status'])
                    Domoticz.Debug(str.format("[partition {0}] state has updated: {1}", partitionNumber, json.dumps(evl_ResponseTypes[code]['status'])))

                    '''Log the user who last armed or disarmed the alarm'''
                    if code == '700':
                        lastArmedBy = {'last_armed_by_user': int(data[1:5])}
                        self.alarmState['partition'][partitionNumber]['status'].update(lastArmedBy)
                    elif code == '750':
                        lastDisarmedBy = {'last_disarmed_by_user': int(data[1:5])}
                        self.alarmState['partition'][partitionNumber]['status'].update(lastDisarmedBy)

                    return partitionNumber
                else:
                    Domoticz.Error("Invalid data ("+data+") has been passed in the partition update.")
        else:
            Domoticz.Debug(str.format("[partition {0}] state change ignored, invalid partition number.", partitionNumber))

    def handle_keypad_led_change(self, code, data):
        """Event 510-511, detail the led state and led flash state respectively."""
        parse = re.match('^[0-9A-F]{2}$', data)
        flash = 'ON'
        if (code == '511'):
            flash = 'FLASH'
        if parse:
            mask = int(data,16)
            for LED in evl_LedMask:
                if (mask & evl_LedMask[LED]):
                    Domoticz.Log("Keypad LED "+flash+": "+LED)
            return 1
        else:
            Domoticz.Error("Invalid data ("+data+") has been passed for code: '"+code+"'.")

    def handle_keypad_update(self, code, data):
        """Handle general- non partition based info"""
        for part in self.alarmState['partition']:
            self.alarmState['partition'][part]['status'].update(evl_ResponseTypes[code]['status'])
        Domoticz.Debug(str.format("[All partitions] state has updated: {0}", json.dumps(evl_ResponseTypes[code]['status'])))

    def handle_verbose_status(self, code, data):
        """Event 849, This command is issued when a trouble appears on the system and roughly every 5 minutes until the trouble is cleared.."""
        parse = re.match('^[0-9]{2}$', data)
        if parse:
            mask = int(data,16)
            for trouble in evl_TroubleMask:
                if (mask & evl_TroubleMask[trouble]):
                    Domoticz.Log("Verbose Trouble Status: "+trouble)
            return 1
        else:
            Domoticz.Error("Invalid data ("+data+") has been passed for code: '"+code+"'.")

    def handle_poll_response(self, code, data):
        """Handle command responses"""
        Domoticz.Debug("'"+evl_ResponseTypes[code]['name']+"' command acknowledged.")

    def handle_time_response(self, code, data):
        """Handle time responses, e.g. '2128042318'"""
        parse = re.match('^[0-9]{10}$', data)
        if parse:
            try:
                theTime = datetime.now()
                theTime.replace(hour=int(data[:2]),minute=int(data[2:4]),month=int(data[4:6]),day=int(data[6:8]),year=2000+int(data[8:]))
                message = '{:02}:{:02} {:02}/{:02}/{:04}'.format(theTime.hour, theTime.minute, theTime.day, theTime.month, theTime.year)
                Domoticz.Log("Received time synchronization ('"+message+"')")
            except ValueError:
                Domoticz.Error(str.format("Error processing time synchronization: '{0}'. Skipping.", data))
        else:
            Domoticz.Error("Invalid time data ("+data+") has been passed for code: '"+code+"'.")

    def handle_output_pressed(self, code, data):
        """Command Output Pressed, code: '912', Data: <partition><output> e.g '11'"""
        part = data[:1]
        output = data[-1:]
        deviceNo = OUTPUT_BASE+int(data)
        if (not deviceNo in Devices):
            Domoticz.Device(Name="Partition "+part+" Output "+output, Unit=deviceNo, Type=17, Subtype=0, Switchtype=9).Create()
            Domoticz.Log("Created Command Output device for Partition "+part+" Output "+output)
        UpdateDevice(deviceNo, 1, "On", False)
        Domoticz.Log("Command output pressed for Partition "+part+" Output "+output)

    def handle_system_response_error(self, code, data):
        """Handle system error responses"""
        try:
            Domoticz.Error(str.format("System Error: '{0}' with data: {1}", evl_ResponseTypes[code]['name'], data))
            Domoticz.Error(str.format("---> Details: '{0}'", evl_Errors[data]['description'] ))
        except:
            Domoticz.Error("Response error not handled: '"+code+"' command, data: "+data)

    def handle_command_response_error(self, code, data):
        """Handle command error responses"""
        try:
            Domoticz.Error(str.format("System Error: '{0}' with data: {1}", evl_ResponseTypes[code]['name'], data))
        except:
            Domoticz.Error("Response error not handled: '"+code+"' command, data: "+data)

    def handle_message_response_error(self, code, data):
        """Handle command message responses"""
        try:
            Domoticz.Log(str.format("Message {0}: '{1}' with data: {2}", code, evl_ResponseTypes[code]['name'], data))
        except:
            Domoticz.Error("Response message not handled: '"+code+"' command, data: "+data)

    def handle_login(self, command, data):
        if (data == "0"):
            Domoticz.Error("Login Unsuccessful.")
        elif (data == "1"):
            Domoticz.Log("Login Successful.")
            self.alarmConn.Send(CreateChecksum(evl_Commands['StatusReport']))
            self.alarmConn.Send(CreateChecksum(evl_Commands['TimeBroadcast']), 3)
            self.alarmConn.Send(CreateChecksum(evl_Commands['PartitionKeypress']+'1*1#'), 5)
            self.alarmConn.Send(CreateChecksum(evl_Commands['DumpZoneTimers']), 8)
        elif (data == "3"):
            message = evl_Commands['Login']+Parameters["Password"]
            message = CreateChecksum(message)
            Domoticz.Debug("Sending Login Response.")
            self.alarmConn.Send(message)

    def notHandled(self, command, data):
        Domoticz.Error("EnvisaLink returned unhandled message: '"+command+"', ignored. Data: '"+data+"'")

    def SyncDevices(self, TimedOut):
        # Make sure that the Domoticz devices are in sync (by definition, the device is connected)
        if (1 in Devices):
            UpdateDevice(1, self.playerState, self.mediaDescrption, TimedOut)
        if (2 in Devices):
            if (Devices[2].nValue != self.mediaLevel) or (Devices[2].TimedOut != TimedOut):
                UpdateDevice(2, self.mediaLevel, str(self.mediaLevel), TimedOut)
        if (4 in Devices):
            if (self.playerState == 4) or (self.playerState == 5):
                UpdateDevice(4, 2, str(self.percentComplete), TimedOut)
            else:
                UpdateDevice(4, 0, str(self.percentComplete), TimedOut)
        return

def ValidChecksum(message):
    checkSum = 0
    for c in message[:-2]:
        checkSum = checkSum + ord(c)
    checkSum = 255 & checkSum
    try:
        origChecksum = int(message[-2:],16)
    except:
        return False
    if (checkSum == origChecksum):
        return True
    return False

def CreateChecksum(message):
    checkSum = 0
    for c in message:
        checkSum = checkSum + ord(c)
    return message+('%02X'% checkSum)[-2:]+"\r\n"

global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onSecurityEvent(Unit, Level, Description):
    global _plugin
    _plugin.onSecurityEvent(Unit, Level, Description)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Settings count: " + str(len(Settings)))
    for x in Settings:
        Domoticz.Debug( "'" + x + "':'" + str(Settings[x]) + "'")
    Domoticz.Debug("Image count: " + str(len(Images)))
    for x in Images:
        Domoticz.Debug( "'" + x + "':'" + str(Images[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
        Domoticz.Debug("Device Image:     " + str(Devices[x].Image))
    return

def UpdateDevice(Unit, nValue, sValue, TimedOut):
    # Make sure that the Domoticz device still exists (they can be deleted) before updating it
    if (Unit in Devices):
        if (Devices[Unit].nValue != nValue) or (Devices[Unit].sValue != sValue) or (Devices[Unit].TimedOut != TimedOut):
            Devices[Unit].Update(nValue=nValue, sValue=str(sValue), TimedOut=TimedOut)
            Domoticz.Debug("Update "+str(nValue)+":'"+str(sValue)+"' ("+Devices[Unit].Name+")")
    return
