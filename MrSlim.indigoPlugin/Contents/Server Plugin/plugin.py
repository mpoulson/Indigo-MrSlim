#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import indigo
import os
import sys
import random
import re
import urllib2
import urllib
import time
from MrSlim import MrSlim
from copy import deepcopy
import versionCheck.versionCheck as VS
# Need json support; Use "simplejson" for Indigo support
try:
	import simplejson as json
except:
	import json

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.

################################################################################
kHvacModeEnumToStrMap = {
	indigo.kHvacMode.Cool				: u"cool",
	indigo.kHvacMode.Heat				: u"heat",
	indigo.kHvacMode.HeatCool			: u"auto", # Not Supported
	indigo.kHvacMode.Off				: u"off",
	indigo.kHvacMode.ProgramHeat		: u"program heat", #Not supported
	indigo.kHvacMode.ProgramCool		: u"program cool", #Not supported
	indigo.kHvacMode.ProgramHeatCool	: u"program auto" # Not supported
}

kFanModeEnumToStrMap = {
	indigo.kFanMode.AlwaysOn			: u"always on",
	indigo.kFanMode.Auto				: u"auto"
}
map_to_indigo_fan_mode={'On':indigo.kFanMode.AlwaysOn,
						'Circulate':indigo.kFanMode.AlwaysOn,
						'Auto':indigo.kFanMode.Auto}

map_to_indigo_hvac_mode={'cool':indigo.kHvacMode.Cool,
						'heat':indigo.kHvacMode.Heat,
						'auto':indigo.kHvacMode.HeatCool,
						'range':indigo.kHvacMode.HeatCool,
						'off':indigo.kHvacMode.Off}

def _lookupActionStrFromHvacMode(hvacMode):
	return kHvacModeEnumToStrMap.get(hvacMode, u"unknown")

def _lookupActionStrFromFanMode(fanMode):
	return kFanModeEnumToStrMap.get(fanMode, u"unknown")

################################################################################
class Plugin(indigo.PluginBase):
	########################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
		self.MrSlim = MrSlim(self)
		self.debug = pluginPrefs.get("debug", False)
		self.UserID = None
		self.Password = None
		self.deviceList = {}
		self.loginFailed = False
		self.restartCount = 0

	######################
	def _changeTempSensorValue(self, dev, index, value, keyValueList):
		# Update the temperature value at index. If index is greater than the "NumTemperatureInputs"
		# an error will be displayed in the Event Log "temperature index out-of-range"
		stateKey = u"temperatureInput" + str(index)
		keyValueList.append({'key':stateKey, 'value':value, 'uiValue':"%d °F" % (value)})
		self.debugLog(u"\"%s\" updating %s %d" % (dev.name, stateKey, value))

	######################
	# Poll all of the states from the thermostat and pass new values to
	# Indigo Server.
	def _refreshStatesFromHardware(self, dev):

		thermostatId = dev.pluginProps["thermostatId"]
		self.debugLog(u"Getting data for thermostatId: %s" % thermostatId)

		thermostat = MrSlim.GetThermostat(self.MrSlim,thermostatId)

		if not hasattr(thermostat, 'name'):
			self.restartCount = 2000000 # Force restart
			return
		
		if thermostat.name == None:
			indigo.server.log(u"Error Getting data from server")
			return
		
		self.debugLog(u"Device Name: %s" % thermostat.name)
		self.debugLog(u"***Device SystemSwitch: %s" % map_to_indigo_hvac_mode[thermostat.SystemSwitch])

		self.debugLog(u"Device State: %s" % thermostat.StatusHeat)

		try: self.updateStateOnServer(dev, "name", thermostat.friendlyName)
		except: self.de (dev, "name")
		try: self.updateStateOnServer(dev, "setpointHeat", float(thermostat.HeatSetPoint))
		except: self.de (dev, "setpointHeat")
		try: self.updateStateOnServer(dev, "setpointCool", float(thermostat.CoolSetPoint))
		except: self.de (dev, "setpointCool")
		try: self.updateStateOnServer(dev, "hvacOperationMode", map_to_indigo_hvac_mode[thermostat.SystemSwitch])
		except: self.de (dev, "hvacOperationMode")

		try: self.updateStateOnServer(dev, "thermostatMode", _lookupActionStrFromHvacMode(thermostat.SystemSwitch))
		except: self.de (dev, "thermostatMode")

		#Check to see if the device supports FANs.  
		isFanEnabled = dev.pluginProps.get("SupportsHvacFanMode", None)
		if isFanEnabled:
			try: self.updateStateOnServer(dev, "hvacFanMode", map_to_indigo_fan_mode[thermostat.Fan.position])
			except: self.de (dev, "hvacFanMode")
		
		try: self.updateStateOnServer(dev, "maxCoolSetpoint", thermostat.CoolUpperSetptLimit)
		except: self.de (dev, "maxCoolSetpoint")
		try: self.updateStateOnServer(dev, "maxHeatSetpoint", thermostat.HeatUpperSetptLimit)
		except: self.de (dev, "maxHeatSetpoint")
		try: self.updateStateOnServer(dev, "minCoolSetpoint", thermostat.CoolLowerSetptLimit)
		except: self.de (dev, "minCoolSetpoint")
		try: self.updateStateOnServer(dev, "minHeatSetpoint", thermostat.HeatLowerSetptLimit)
		except: self.de (dev, "minHeatSetpoint")
		try: self.updateStateOnServer(dev, "temperatureInput1", thermostat.DispTemperature)
		except: pass
		if thermostat.IndoorHumidity:
			try: self.updateStateOnServer(dev, "IndoorHumidity", thermostat.IndoorHumidity)
			except: self.de (dev, "IndoorHumidity")
		if thermostat.OutdoorTemp:
			try: self.updateStateOnServer(dev, "OutdoorTemp", thermostat.OutdoorTemp)
			except: self.de (dev, "OutdoorTemp")
		if thermostat.OutdoorHumidity or thermostat.OutdoorHumidity != 128.0000:
			try: self.updateStateOnServer(dev, "OutdoorHumidity", thermostat.OutdoorHumidity)
			except: self.de (dev, "OutdoorHumidity")

		if  _lookupActionStrFromHvacMode(dev.states["hvacOperationMode"]) == "heat":
			self.updateStateOnServer(dev, "hvacHeaterIsOn", True)
			self.updateStateOnServer(dev, "hvacCoolerIsOn", False)
		elif _lookupActionStrFromHvacMode(dev.states["hvacOperationMode"]) == "cool":
			self.updateStateOnServer(dev, "hvacHeaterIsOn", False)
			self.updateStateOnServer(dev, "hvacCoolerIsOn", True)
		else:
			self.updateStateOnServer(dev, "hvacHeaterIsOn", False)
			self.updateStateOnServer(dev, "hvacCoolerIsOn", False)

	def updateStateOnServer(self, dev, state, value):
		if dev.states[state] != value:
			self.debugLog(u"Updating Device: %s, State: %s, Value: %s" % (dev.name, state, value))
			dev.updateStateOnServer(state, value)

	def de (self, dev, value):
		self.errorLog ("[%s] No value found for device: %s, field: %s" % (time.asctime(), dev.name, value))

	######################
	# Process action request from Indigo Server to change main thermostat's main mode.
	def _handleChangeHvacModeAction(self, dev, newHvacMode):
		# Command hardware module (dev) to change the thermostat mode here:
		self.debugLog(u"_handleChangeHvacModeAction - newHvacMode: %s" % newHvacMode)

		sendSuccess = False
		thermostatId = dev.pluginProps["thermostatId"]
		thermostat = MrSlim.GetThermostat(self.MrSlim,thermostatId)
		actionStr = _lookupActionStrFromHvacMode(newHvacMode)
		if actionStr == "auto":
			indigo.server.log(u"Device \"%s\" does not support mode %s" % (dev.name, actionStr), isError=True)
			return
		response = self.MrSlim.SetThermostatState(thermostat, actionStr)

		if actionStr == "heat":
			dev.updateStateOnServer("hvacCoolerIsOn", False)
			dev.updateStateOnServer("hvacHeaterIsOn", True)
		else:
			dev.updateStateOnServer("hvacCoolerIsOn", True)
			dev.updateStateOnServer("hvacHeaterIsOn", False)

		#self.debugLog(u"Response: %s" % response)
		sendSuccess = True

		if sendSuccess:
			# If success then log that the command was successfully sent.
			indigo.server.log(u"sent \"%s\" mode change to %s" % (dev.name, actionStr))

			# And then tell the Indigo Server to update the state.
			if "hvacOperationMode" in dev.states:
				dev.updateStateOnServer("hvacOperationMode", newHvacMode)
		else:
			# Else log failure but do NOT update state on Indigo Server.
			indigo.server.log(u"send \"%s\" mode change to %s failed" % (dev.name, actionStr), isError=True)

	# Process action request from Indigo Server to change a cool/heat setpoint.
	def _handleChangeSetpointAction(self, dev, newSetpoint, logActionName, stateKey):
		self.debugLog(u"_handleChangeSetpointAction - StateKey: %s" % stateKey)

		sendSuccess = False
		thermostatId = dev.pluginProps["thermostatId"]
		self.debugLog(u"Getting data for thermostatId: %s" % thermostatId)
		self.debugLog(u"NewSetpoint: %s" % newSetpoint)

		thermostat = MrSlim.GetThermostat(self.MrSlim,thermostatId)

		if stateKey == u"setpointCool":
			# Command hardware module (dev) to change the cool setpoint to newSetpoint here:
			# if newSetpoint > dev.states["maxCoolSetpoint"]:
			# 	newSetpoint = dev.states["maxCoolSetpoint"]
			# elif newSetpoint > dev.states["minCoolSetpoint"]:
			# 	newSetpoint = dev.states["minCoolSetpoint"]

			self.MrSlim.SetThermostatCoolSetpoint(thermostat,newSetpoint)
			sendSuccess = True			# Set to False if it failed.
		elif stateKey == u"setpointHeat":
			# if newSetpoint < dev.states["maxHeatSetpoint"]:
			# 	newSetpoint = dev.states["maxHeatSetpoint"]
			# elif newSetpoint > dev.states["minHeatSetpoint"]:
			# 	newSetpoint = dev.states["minHeatSetpoint"]

			self.MrSlim.SetThermostatHeatSetpoint(thermostat,newSetpoint)
			sendSuccess = True			# Set to False if it failed.

		if sendSuccess:
			# If success then log that the command was successfully sent.
			indigo.server.log(u"sent \"%s\" %s to %.1f°" % (dev.name, logActionName, float(newSetpoint)))

			# And then tell the Indigo Server to update the state.
			if stateKey in dev.states:
				dev.updateStateOnServer(stateKey, newSetpoint, uiValue="%.1f °F" % float(newSetpoint))
		else:
			# Else log failure but do NOT update state on Indigo Server.
			indigo.server.log(u"send \"%s\" %s to %.1f° failed" % (dev.name, logActionName, float(newSetpoint)), isError=True)
	def _handleSetFanModeAction(self, dev, fanMode, logActionName, stateKey):
		self.debugLog(u"handleSetFanModeAction - StateKey: %s" % stateKey)

		sendSuccess = False
		thermostatId = dev.pluginProps["thermostatId"]
		self.debugLog(u"Getting data for thermostatId: %s" % thermostatId)
		self.debugLog(u"FanMode: %s" % fanMode)
	
		thermostat = MrSlim.GetThermostat(self.MrSlim,thermostatId)
		self.debugLog(u"Thermostat Fan CanControl Value: %s" % thermostat.Fan.canControl)

		if thermostat.Fan.canControl != u"true":
			indigo.server.log(u"Unable to use fan Control on \"%s\"  because the Server said canControl = %s°" % (dev.name, thermostat.Fan.canControl))
		else:
			if stateKey == u"fanMode":
				self.MrSlim.SetThermostatFanMode(thermostat,fanMode)
				sendSuccess = True			# Set to False if it failed.
			
			if sendSuccess:
				# If success then log that the command was successfully sent.
				indigo.server.log(u"sent \"%s\" %s to %s°" % (dev.name, logActionName, fanMode))

				# And then tell the Indigo Server to update the state.
				if stateKey in dev.states:
					dev.updateStateOnServer(stateKey, fanMode, uiValue="%s" % fanMode)
			else:
				# Else log failure but do NOT update state on Indigo Server.
				indigo.server.log(u"send \"%s\" %s to %.1f° failed" % (dev.name, logActionName, fanMode), isError=True)

	########################################
	def startup(self):
		self.debugLog(u"MrSlim startup called")
		self.debug = self.pluginPrefs.get('showDebugInLog', False)

		self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', 24)) * 60.0 * 60.0
		self.debugLog(u"updateFrequency = " + str(self.updateFrequency))
		self.next_update_check = time.time()
		self.login(False)

	def login(self, force):
		if self.MrSlim.startup(force) == False:
			indigo.server.log(u"Login to TCC site failed.  Canceling processing!", isError=True)
			self.loginFailed = True
			return
		else:
			self.loginFailed = False

		self.buildAvailableDeviceList()

	def shutdown(self):
		self.debugLog(u"shutdown called")
		self.StopThread = True

	########################################
	def runConcurrentThread(self):
		try:
			while True:
				if self.loginFailed == False:
					if (self.updateFrequency > 0.0) and (time.time() > self.next_update_check):
						self.next_update_check = time.time() + self.updateFrequency
						self.version_check()

					for dev in indigo.devices.iter("self"):
						if not dev.enabled:
							continue

						# Plugins that need to poll out the status from the thermostat
						# could do so here, then broadcast back the new values to the
						# Indigo Server.
						self._refreshStatesFromHardware(dev)
						self.restartCount = self.restartCount + 1

				if (self.restartCount > 10000):
					self.restartCount = 0
					indigo.server.log(u"Memory Leak Prevention. Restarting Plugin. - This will happen until I find and fix the leak")
					serverPlugin = indigo.server.getPlugin(self.pluginId)
					serverPlugin.restart(waitUntilDone=False)
					break
				self.sleep(7)
		except self.StopThread:
			self.debugLog("shutdown requested")
			pass	# Optionally catch the StopThread exception and do any needed cleanup.

	########################################
	def validateDeviceConfigUi(self, valuesDict, typeId, devId):
		indigo.server.log(u"validateDeviceConfigUi \"%s\"" % (valuesDict))
		return (True, valuesDict)

	def validatePrefsConfigUi(self, valuesDict):
		self.debugLog(u"Vaidating Plugin Configuration")
		errorsDict = indigo.Dict()
		if len(errorsDict) > 0:
			self.errorLog(u"\t Validation Errors")
			return (False, valuesDict, errorsDict)
		else:
			self.debugLog(u"\t Validation Succesful")
			return (True, valuesDict)
		return (True, valuesDict)

	########################################
	def deviceStartComm(self, dev):
		if self.loginFailed == True:
			return

		# Called when communication with the hardware should be established.
		# Here would be a good place to poll out the current states from the
		# thermostat. If periodic polling of the thermostat is needed (that
		# is, it doesn't broadcast changes back to the plugin somehow), then
		# consider adding that to runConcurrentThread() above.
		self.initDevice(dev)

		dev.stateListOrDisplayStateIdChanged()

	def deviceStopComm(self, dev):
		# Called when communication with the hardware should be shutdown.
		pass

	########################################
	# Thermostat Action callback
	######################
	# Main thermostat action bottleneck called by Indigo Server.
	#Called when the device is changed via UI
	def actionControlThermostat(self, action, dev):
		###### SET HVAC MODE ######
		if action.thermostatAction == indigo.kThermostatAction.SetHvacMode:
			self._handleChangeHvacModeAction(dev, action.actionMode)

		###### SET FAN MODE ######
		elif action.thermostatAction == indigo.kThermostatAction.SetFanMode:
			self._handleSetFanModeAction(dev, action.actionMode)

		###### SET COOL SETPOINT ######
		elif action.thermostatAction == indigo.kThermostatAction.SetCoolSetpoint:
			newSetpoint = action.actionValue
			self._handleChangeSetpointAction(dev, newSetpoint, u"change cool setpoint", u"setpointCool")

		###### SET HEAT SETPOINT ######
		elif action.thermostatAction == indigo.kThermostatAction.SetHeatSetpoint:
			newSetpoint = action.actionValue
			self._handleChangeSetpointAction(dev, newSetpoint, u"change heat setpoint", u"setpointHeat")

		###### DECREASE/INCREASE COOL SETPOINT ######
		elif action.thermostatAction == indigo.kThermostatAction.DecreaseCoolSetpoint:
			newSetpoint = dev.coolSetpoint - action.actionValue
			self._handleChangeSetpointAction(dev, newSetpoint, u"decrease cool setpoint", u"setpointCool")

		elif action.thermostatAction == indigo.kThermostatAction.IncreaseCoolSetpoint:
			newSetpoint = dev.coolSetpoint + action.actionValue
			self._handleChangeSetpointAction(dev, newSetpoint, u"increase cool setpoint", u"setpointCool")

		###### DECREASE/INCREASE HEAT SETPOINT ######
		elif action.thermostatAction == indigo.kThermostatAction.DecreaseHeatSetpoint:
			newSetpoint = dev.heatSetpoint - action.actionValue
			self._handleChangeSetpointAction(dev, newSetpoint, u"decrease heat setpoint", u"setpointHeat")

		elif action.thermostatAction == indigo.kThermostatAction.IncreaseHeatSetpoint:
			newSetpoint = dev.heatSetpoint + action.actionValue
			self._handleChangeSetpointAction(dev, newSetpoint, u"increase heat setpoint", u"setpointHeat")

		###### REQUEST STATE UPDATES ######
		elif action.thermostatAction in [indigo.kThermostatAction.RequestStatusAll, indigo.kThermostatAction.RequestMode,
		indigo.kThermostatAction.RequestEquipmentState, indigo.kThermostatAction.RequestTemperatures, indigo.kThermostatAction.RequestHumidities,
		indigo.kThermostatAction.RequestDeadbands, indigo.kThermostatAction.RequestSetpoints]:
			self._refreshStatesFromHardware(dev)

	########################################
	# Actions defined in MenuItems.xml. In this case we just use these menu actions to
	# simulate different thermostat configurations (how many temperature and humidity
	# sensors they have).
	####################
	def _actionSetMode(self, pluginAction):
		self.debugLog(u"\t Setting Mode: %s" % pluginAction.props.get("mode"))
		dev = indigo.devices[pluginAction.deviceId]
		self._handleChangeHvacModeAction(dev,map_to_indigo_hvac_mode[pluginAction.props.get("mode")])

	def _actionSetpoint(self, pluginAction):
		self.debugLog(u"\t Set %s - Setpoint: %s" % (pluginAction.pluginTypeId, pluginAction.props.get("Temprature")))
		dev = indigo.devices[pluginAction.deviceId]

		self._handleChangeSetpointAction(dev, pluginAction.props.get("Temprature"), "Action Setpoint",pluginAction.pluginTypeId)
	def _actionSetFanMode(self, pluginAction):
		self.debugLog(u"\t Set %s - Setpoint: %s" % (pluginAction.pluginTypeId, pluginAction.props.get("Temprature")))
		dev = indigo.devices[pluginAction.deviceId]

		self._handleSetFanModeAction(dev, pluginAction.props.get("fanmode1"), "Action SetFanMode",pluginAction.pluginTypeId)

	def _resumeProgram(self, pluginAction):
		self.debugLog(u"\t Resuming Program Mode on device")
		dev = indigo.devices[pluginAction.deviceId]
		thermostatId = dev.pluginProps["thermostatId"]
		self.debugLog(u"Getting data for thermostatId: %s" % thermostatId)
		
		thermostat = MrSlim.GetThermostat(self.MrSlim,thermostatId)
		self.MrSlim.SetThermostatStatus(thermostat,'Schedule')

	def closedPrefsConfigUi(self, valuesDict, userCancelled):
		if not userCancelled:
			#Check if Debugging is set
			try:
				self.debug = self.pluginPrefs[u'showDebugInLog']
			except:
				self.debug = False

			try:
				if (self.UserID != self.pluginPrefs["UserID"]) or \
					(self.Password != self.pluginPrefs["Password"]):
					indigo.server.log("[%s] Setting Username/Password." % time.asctime())
					self.UserID = self.pluginPrefs["UserID"]
					self.Password = self.pluginPrefs["Password"]
			except:
				pass

			indigo.server.log("[%s] Processed plugin preferences." % time.asctime())
			self.login(True)
			return True
	def validateDeviceConfigUi(self, valuesDict, typeId, devId):
		self.debugLog(u"validateDeviceConfigUi called with valuesDict: %s" % str(valuesDict))
		# Set the address
		valuesDict["ShowCoolHeatEquipmentStateUI"] = True
		return (True, valuesDict)

	def initDevice(self, dev):
		if dev.deviceTypeId == "MrSlimThermo":
			new_props = dev.pluginProps
			new_props['SupportsHvacFanMode'] = False
			dev.replacePluginPropsOnServer(new_props)

			self.debugLog("Initializing thermostat device: %s" % dev.name)

	def buildAvailableDeviceList(self):
		self.debugLog("Building Available Device List")

		self.deviceList = self.MrSlim.GetDevices()

		indigo.server.log("Number of thermostats found: %i" % (len(self.deviceList)))
		for (k, v) in self.deviceList.iteritems():
			indigo.server.log("\t%s (id: %s)" % (v.name, k))

	def showAvailableThermostats(self):
		indigo.server.log("Number of thermostats found: %i" % (len(self.deviceList)))
		for (id, details) in self.deviceList.iteritems():
			indigo.server.log("\t%s (id: %s)" % (details.friendlyName, id))

	def thermostatList(self, filter, valuesDict, typeId, targetId):
		self.debugLog("thermostatList called")
		deviceArray = []
		deviceListCopy = deepcopy(self.deviceList)
		for existingDevice in indigo.devices.iter("self"):
			for id in self.deviceList:
				self.debugLog("    comparing %s against deviceList item %s" % (existingDevice.pluginProps["thermostatId"],id))
				if existingDevice.pluginProps["thermostatId"] == id:
					self.debugLog("    removing item %s" % (id))
					del deviceListCopy[id]
					break

		if len(deviceListCopy) > 0:
			for (id,value) in deviceListCopy.iteritems():
				deviceArray.append((id,value.friendlyName))
		else:
			if len(self.deviceList):
				indigo.server.log("All thermostats found are already defined")
			else:
				indigo.server.log("No thermostats were discovered on the network - select \"Rescan for Thermostats\" from the plugin's menu to rescan")

		self.debugLog("    thermostatList deviceArray:\n%s" % (str(deviceArray)))
		return deviceArray

	def thermostatSelectionChanged(self, valuesDict, typeId, devId):
		self.debugLog("thermostatSelectionChanged")
		if valuesDict["thermostat"] in self.deviceList:
			selectedThermostatData = self.deviceList[valuesDict["thermostat"]]
			valuesDict["address"] = valuesDict["thermostat"]
			valuesDict["thermostatId"] = valuesDict["thermostat"]
			valuesDict["name"] = selectedThermostatData.name
			valuesDict["friendlyName"] = selectedThermostatData.friendlyName
		self.debugLog("    thermostatSelectionChanged valuesDict to be returned:\n%s" % (str(valuesDict)))
		return valuesDict
	##########################################
	def version_check(self):
		VS.versionCheck(self.pluginId,self.pluginVersion,indigo,printToLog="log")
