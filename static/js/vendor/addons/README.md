three.js r186 addons, copied unmodified from three@0.186.0/examples/jsm to match
the vendored ../three.module.js + ../three.core.js (also r186). They import the
bare specifier "three", so pages using them declare an importmap pointing
"three" at /static/js/vendor/three.module.js (see templates/home_world.html).
Upgrade three and these files together.
