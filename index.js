'use strict';
const fs = require('fs');
const path = require('path');
const exec = require('child_process').exec;
const yaml = require('js-yaml');

const PLUGIN_PATH = __dirname;
const CONFIG_YAML = path.join(PLUGIN_PATH, 'quadify', 'config.yaml');

module.exports = function (context) {
    const self = this;

    // Load YAML config
    self.loadConfig = function() {
        try {
            const doc = yaml.load(fs.readFileSync(CONFIG_YAML, 'utf8'));
            return doc;
        } catch (e) {
            self.log('warn', 'Config not found, using default');
            return {};
        }
    };

    // Save YAML config
    self.saveConfig = function(config) {
        fs.writeFileSync(CONFIG_YAML, yaml.dump(config), 'utf8');
    };

    // Logger
    self.log = function(level, msg) {
        console.log(`[QuadifyPlugin][${level}] ${msg}`);
    };

    // Exposed plugin methods
    self.onStart = function() {
        self.log('info', 'Quadify plugin started');
        // Start your Python backend here if needed, eg spawn child process
    };

    self.onStop = function() {
        self.log('info', 'Quadify plugin stopped');
        // Stop any child process if needed
    };

    // UIConfig load
    self.getUIConfig = function (callback) {
        const lang_code = 'en';
        fs.readFile(path.join(__dirname, 'UIConfig.json'), 'utf8', (err, data) => {
            if (err) return callback(err);
            callback(null, JSON.parse(data));
        });
    };

    // MCP23017 auto-detect
    self.autoDetectMCP = function (data, callback) {
        exec('i2cdetect -y 1', (error, stdout) => {
            if (error) {
                callback({ success: false, error: error.toString() });
            } else {
                // Look for address like "20", "21", etc in the output
                const match = stdout.match(/\b2[0-7]\b/);
                if (match) {
                    const address = `0x${match[0]}`;
                    let config = self.loadConfig();
                    config.mcp23017_address = address;
                    self.saveConfig(config);
                    callback({ success: true, address });
                } else {
                    callback({ success: false, error: 'No MCP23017 found' });
                }
            }
        });
    };

    // Rotary config save
    self.updateRotaryConfig = function (data, callback) {
        let config = self.loadConfig();
        config.pins = config.pins || {};
        config.pins.clk_pin = parseInt(data.clk_pin) || 13;
        config.pins.dt_pin = parseInt(data.dt_pin) || 5;
        config.pins.sw_pin = parseInt(data.sw_pin) || 6;
        config.rotary_enabled = !!data.rotary_enabled;
        self.saveConfig(config);
        callback({ success: true });
    };

    // MCP config save
    self.updateMcpConfig = function (data, callback) {
        let config = self.loadConfig();
        if (data.mcp23017_address) config.mcp23017_address = data.mcp23017_address;
        self.saveConfig(config);
        callback({ success: true });
    };

    // IR config save
    self.updateIrConfig = function (data, callback) {
        let config = self.loadConfig();
        config.ir_enabled = !!data.ir_enabled;
        config.ir_type = data.ir_type;
        config.ir_gpio = parseInt(data.ir_gpio) || 26;
        self.saveConfig(config);
        callback({ success: true });
    };

    // IR apply (dummy)
    self.applyIrConfig = function (data, callback) {
        // Here you would copy lircd.conf/lircrc and restart services, etc.
        callback({ success: true, msg: 'IR config applied (dummy handler)' });
    };

    return self;
};
