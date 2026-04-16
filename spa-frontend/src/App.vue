<script setup lang="ts">
import { onMounted, watchEffect } from 'vue';
import DefaultLayout from './layouts/DefaultLayout.vue';
import { useAuthStore } from './stores/auth';
import { useNavStore } from './stores/nav';
import { useTheme } from './theme/useTheme';

const auth = useAuthStore();
const nav = useNavStore();
const theme = useTheme();

watchEffect(() => {
  document.title = nav.courseName === 'REF' ? 'REF' : `REF - ${nav.courseName}`;
});

onMounted(async () => {
  theme.init();
  await Promise.all([auth.hydrate(), nav.hydrate()]);
});
</script>

<template>
  <DefaultLayout>
    <RouterView />
  </DefaultLayout>
</template>
