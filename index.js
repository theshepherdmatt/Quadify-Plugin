'use strict';

const libQ = require('kew');
const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const exec = require('child_process').exec;

module.exports = ControllerQuadify;

function ControllerQuadify(context) {
    this.context = context;
    this.commandRouter = context.coreCommand;
    this.logger = this.commandRouter.logger;
    this.configManager = this.context.configManager;

    this.pluginPath = __dirname;
    this.configYamlPath = path.join(this.pluginPath, 'quadify', 'config.yaml');
}

// --- Plugin Lifecycle Methods ---

ControllerQuadify.prototype.onVolumioStart = function () {
    this.logger.info('[QuadifyPlugin] onVolumioStart');
    // Load config or perform other startup actions here
    return libQ.resolve();
};

ControllerQuadify.prototype.onStart = function () {
    this.logger.info('[QuadifyPlugin] onStart');
    // You could start your Python process here if you want to tie it to plugin enable
    return libQ.resolve();
};

ControllerQuadify.prototype.onStop = function () {
    this.logger.info('[QuadifyPlugin] onStop');
    // Cleanup, stop any Python processes, etc.
    return libQ.resolve();
};

ControllerQuadify.prototype.onRestart = function () {
    this.logger.info('[QuadifyPlugin] onRestart');
    // Actions before Volumio restarts
};

ControllerQuadify.prototype.onInstall = function () {
    this.logger.info('[QuadifyPlugin] onInstall');
    // Actions after plugin install
};

ControllerQuadify.prototype.onUninstall = function () {
    this.logger.info('[QuadifyPlugin] onUninstall');
    // Cleanup when plugin is uninstalled
};

// --- UIConfig Methods ---

ControllerQuadify.prototype.getUIConfig = function () {
    const defer = libQ.defer();
    const lang_code = this.commandRouter.sharedVars.get('language_code') || 'en';

    this.commandRouter.i18nJson(
        path.join(__dirname, '/i18n/strings_' + lang_code + '.json'),
        path.join(__dirname, '/i18n/strings_en.json'),
        path.join(__dirname, '/UIConfig.json')
    ).then((uiconf) => {
        // You could inject dynamic config here if desired
        defer.resolve(uiconf);
    }).fail((e) => {
        this.logger.error('[QuadifyPlugin] getUIConfig error: ' + e);
        defer.reject(new Error());
    });

    return defer.promise;
};

// --- Config Loader/Saver ---

ControllerQuadify.prototype.loadConfig = function () {
    try {
        const doc = yaml.load(fs.readFileSync(this.configYamlPath, 'utf8'));
        return doc || {};
    } catch (e) {
        this.logger.warn('[QuadifyPlugin] Config not found, using default');
        return {};
    }
};

ControllerQuadify.prototype.saveConfig = function (config) {
    fs.writeFileSync(this.configYamlPath, yaml.dump(config), 'utf8');
};

// --- API Endpoints for UI buttons ---

ControllerQuadify.prototype.updateMcpConfig = function (data, callback) {
    let config = this.loadConfig();
    if (data.mcp23017_address) config.mcp23017_address = data.mcp23017_address;
    this.saveConfig(config);
    callback({ success: true });
};

ControllerQuadify.prototype.autoDetectMCP = function (data, callback) {
    exec('i2cdetect -y 1', (error, stdout) => {
        if (error) {
            callback({ success: false, error: error.toString() });
        } else {
            const match = stdout.match(/\b2[0-7]\b/);
            if (match) {
                const address = `0x${match[0]}`;
                let config = this.loadConfig();
                config.mcp23017_address = address;
                this.saveConfig(config);
                callback({ success: true, address });
            } else {
                callback({ success: false, error: 'No MCP23017 found' });
            }
        }
    });
};

ControllerQuadify.prototype.updateRotaryConfig = function (data, callback) {
    let config = this.loadConfig();
    config.pins = config.pins || {};
    config.pins.clk_pin = parseInt(data.clk_pin) || 13;
    config.pins.dt_pin = parseInt(data.dt_pin) || 5;
    config.pins.sw_pin = parseInt(data.sw_pin) || 6;
    config.rotary_enabled = !!data.rotary_enabled;
    this.saveConfig(config);
    callback({ success: true });
};

ControllerQuadify.prototype.updateIrConfig = function (data, callback) {
    let config = this.loadConfig();
    config.ir_enabled = !!data.ir_enabled;
    config.ir_type = data.ir_type;
    config.ir_gpio = parseInt(data.ir_gpio) || 26;
    this.saveConfig(config);
    callback({ success: true });
};

ControllerQuadify.prototype.applyIrConfig = function (data, callback) {
    // Here you would copy lircd.conf/lircrc and restart services, etc.
    callback({ success: true, msg: 'IR config applied (dummy handler)' });
};

// --- Utility: required by Volumio for plugin config UI ---
ControllerQuadify.prototype.getConfigurationFiles = function () {
    return ['quadify/config.yaml'];
};
