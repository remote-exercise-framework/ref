<script setup lang="ts">
import { onMounted, watchEffect } from 'vue';
import DefaultLayout from './layouts/DefaultLayout.vue';
import { useNavStore } from './stores/nav';
import { useTheme } from './theme/useTheme';

const nav = useNavStore();
const theme = useTheme();

watchEffect(() => {
  document.title = nav.courseName === 'REF' ? 'REF' : `REF - ${nav.courseName}`;
});

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
