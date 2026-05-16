module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      // Reanimated 4 (used in SDK 54+) split worklets into its own package.
      // The plugin moved here from `react-native-reanimated/plugin`. Must be
      // last in the plugin list.
      'react-native-worklets/plugin',
    ],
  };
};
