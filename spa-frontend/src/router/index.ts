import { createRouter, createWebHistory } from 'vue-router';

const routes = [
  {
    path: '/',
    redirect: '/register',
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('../pages/Register.vue'),
    meta: { label: 'REGISTER' },
  },
  {
    path: '/restore-key',
    name: 'restore-key',
    component: () => import('../pages/RestoreKey.vue'),
    meta: { label: 'RESTORE KEY' },
  },
  {
    path: '/scoreboard',
    name: 'scoreboard',
    component: () => import('../pages/Scoreboard.vue'),
    meta: { label: 'SCOREBOARD' },
  },
];

export default createRouter({
  history: createWebHistory('/spa/'),
  routes,
});
