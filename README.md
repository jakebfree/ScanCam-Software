ScanCam-Software
================

Controls 3-axis camera translation and video acquisition system. System consists of Zaber motion control devices that position an industrial vision camera mounted with a microscope lens and periodically record images or short video clips at multiple pre-defined positions across biological cultures.

Motion Control and Frame of Reference
---------------------------------------------
Due to spatial constraints in the original experiment application, the "X-Y" translation from one culture location to the next was implemented using a linear slide and a rotary stage to affect an "X-Theta" configuration. This allows the camera to sweep very close to the floor and ceiling of the experiment enclosure without the system interference created when using comparable linear axes for the "Y" translation.

The frame of reference for the culture imaging locations, however, is specified in standard cartesian X-Y coordinates in order to be more easy to define and understand in human-accessible terms. It also lends itself well to future implementations (e.g. use in SABL) that will be less space-constrained and can use the more obvious 3-linear axis implementation.

The Zaber devices use stepper motors and integrated controllers. The control computer communicates with the motion devices via RS-232 serial communication that is effectively bussed in hardware by having the first device repeat the communications to daisy-chained devices downstream. hgomersall (also on github) created a python library for communicating with zaber devices. This library was imported into the scancam repo and updated to support rotary stages as well as some other minor helpful features.
