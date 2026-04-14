<script setup lang="ts">
import { onMounted } from 'vue';
import DefaultLayout from './layouts/DefaultLayout.vue';
import { useNavStore } from './stores/nav';
import { useTheme } from './theme/useTheme';

const nav = useNavStore();
const theme = useTheme();

onMounted(async () => {
  theme.init();
  await nav.hydrate();
});
</script>

<template>
  <DefaultLayout>
    <RouterView />
  </DefaultLayout>
</template>
