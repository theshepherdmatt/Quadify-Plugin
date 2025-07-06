// test-write.js
const Vconf = require('v-conf');
const path = require('path');

const configPath = '/data/plugins/music_service/quadify/config.json';

const conf = new Vconf();
conf.loadFile(configPath); // Loads or creates if missing

conf.set('testKey', 'hello world');
conf.set('anotherKey', 123);

conf.save(configPath);
console.log('Saved config:', require(configPath));

