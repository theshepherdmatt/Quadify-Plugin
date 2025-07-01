'use strict';
const libQ = require('kew');
const fs = require('fs-extra');
const yaml = require('js-yaml');
const path = require('path');

function ControllerQuadify(context) {
    var self = this;

    self.context = context;
    self.commandRouter = self.context.coreCommand;
    self.logger = self.context.logger;
    self.configManager = self.context.configManager;

    // Path to config.yaml in your plugin folder
    self.configYamlPath = path.join(__dirname, 'quadify', 'config.yaml');
}

ControllerQuadify.prototype.onVolumioStart = function() {
    return libQ.resolve();
};

ControllerQuadify.prototype.onStart = function() {
    this.logger.info('[Quadify] Plugin started');
    return libQ.resolve();
};

ControllerQuadify.prototype.onStop = function() {
    this.logger.info('[Quadify] Plugin stopped');
    return libQ.resolve();
};

ControllerQuadify.prototype.getConfigurationFiles = function() {
    return ['config.json'];
};

// UIConfig loader with i18n
ControllerQuadify.prototype.getUIConfig = function() {
    var self = this;
    var defer = libQ.defer();
    var lang_code = self.commandRouter.sharedVars.get('language_code');
    self.commandRouter.i18nJson(
        __dirname + '/i18n/strings_' + lang_code + '.json',
        __dirname + '/i18n/strings_en.json',
        __dirname + '/UIConfig.json'
    ).then(function(uiconf) {
        defer.resolve(uiconf);
    }).fail(function() {
        defer.reject(new Error());
    });
    return defer.promise;
};

// --- Add your custom config handlers below ---
// Save MCP config
ControllerQuadify.prototype.updateMcpConfig = function (data) {
    let config = this.loadConfigYaml();
    if (data.mcp23017_address) config.mcp23017_address = data.mcp23017_address;
    this.saveConfigYaml(config);
    this.commandRouter.pushToastMessage('success', 'Quadify', 'MCP23017 address saved!');
    return libQ.resolve();
};

// Auto-detect MCP
ControllerQuadify.prototype.autoDetectMCP = function () {
    var self = this;
    var defer = libQ.defer();
    require('child_process').exec('i2cdetect -y 1', (error, stdout) => {
        if (error) {
            self.commandRouter.pushToastMessage('error', 'Quadify', error.toString());
            defer.reject(error);
        } else {
            const match = stdout.match(/\b2[0-7]\b/);
            if (match) {
                const address = `0x${match[0]}`;
                let config = self.loadConfigYaml();
                config.mcp23017_address = address;
                self.saveConfigYaml(config);
                self.commandRouter.pushToastMessage('success', 'Quadify', 'Detected MCP23017 at ' + address);
                defer.resolve({ success: true, address });
            } else {
                self.commandRouter.pushToastMessage('error', 'Quadify', 'No MCP23017 found');
                defer.reject('No MCP23017 found');
            }
        }
    });
    return defer.promise;
};

// Rotary config
ControllerQuadify.prototype.updateRotaryConfig = function (data) {
    let config = this.loadConfigYaml();
    config.pins = config.pins || {};
    config.pins.clk_pin = parseInt(data.clk_pin) || 13;
    config.pins.dt_pin = parseInt(data.dt_pin) || 5;
    config.pins.sw_pin = parseInt(data.sw_pin) || 6;
    config.rotary_enabled = !!data.rotary_enabled;
    this.saveConfigYaml(config);
    this.commandRouter.pushToastMessage('success', 'Quadify', 'Rotary config saved!');
    return libQ.resolve();
};

// IR config
ControllerQuadify.prototype.updateIrConfig = function (data) {
    let config = this.loadConfigYaml();
    config.ir_enabled = !!data.ir_enabled;
    config.ir_type = data.ir_type;
    config.ir_gpio = parseInt(data.ir_gpio) || 26;
    this.saveConfigYaml(config);
    this.commandRouter.pushToastMessage('success', 'Quadify', 'IR config saved!');
    return libQ.resolve();
};

ControllerQuadify.prototype.applyIrConfig = function () {
    // Implement hardware handling as needed
    this.commandRouter.pushToastMessage('info', 'Quadify', 'IR config applied (stub)');
    return libQ.resolve();
};

// YAML load/save helpers
ControllerQuadify.prototype.loadConfigYaml = function () {
    try {
        return yaml.load(fs.readFileSync(this.configYamlPath, 'utf8')) || {};
    } catch (e) {
        return {};
    }
};
ControllerQuadify.prototype.saveConfigYaml = function (config) {
    fs.writeFileSync(this.configYamlPath, yaml.dump(config), 'utf8');
};

module.exports = ControllerQuadify;
