/*
 * LocalThings
 * Copyright 2026, Geunwon Mo (mokorean@gmail.com)
 *
 * A Homey port of the LocalThings Home Assistant integration
 * (https://github.com/mbillow/localthings): local control of newer-generation
 * Samsung appliances over DTLS/CoAP, with no SmartThings cloud round-trip.
 */

'use strict';

const Homey = require('homey');

class LocalThingsApp extends Homey.App {

  async onInit() {
    this.log('LocalThings app is running...');
  }

}

module.exports = LocalThingsApp;
