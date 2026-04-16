<script setup lang="ts">
import { reactive, ref } from 'vue';
import type { FieldErrors } from '../api/client';
import { ApiError } from '../api/client';
import { restoreKey } from '../api/restoreKey';
import type { KeyResult } from '../api/registration';
import KeyDownloadCard from '../components/KeyDownloadCard.vue';

const form = reactive({ mat_num: '', password: '' });
const submitting = ref(false);
const formError = ref<string | null>(null);
const fieldErrors = ref<FieldErrors>({});
const result = ref<KeyResult | null>(null);

function errsFor(field: string): string[] {
  return fieldErrors.value[field] ?? [];
}

async function onSubmit() {
  formError.value = null;
  fieldErrors.value = {};
  submitting.value = true;
  try {
    result.value = await restoreKey({ ...form });
  } catch (e) {
    if (e instanceof ApiError) {
      formError.value = e.form;
      fieldErrors.value = e.fields;
    } else {
      formError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="term-section term-form-page">
    <div class="term-section-head">
      <h2 class="term-section-title">[ restore key ]</h2>
      <span class="term-eyebrow">// lost your keys?</span>
    </div>

    <div v-if="result" class="term-form-box">
      <KeyDownloadCard :result="result" variant="restore" />
    </div>

    <v-card
      v-else
      class="term-panel term-form-box"
      style="padding: 1.5rem"
    >
      <v-alert
        v-if="formError && Object.keys(fieldErrors).length === 0"
        type="error"
        variant="tonal"
        density="compact"
        style="margin-bottom: 1rem"
      >
        {{ formError }}
      </v-alert>
      <v-form @submit.prevent="onSubmit">
        <v-text-field
          v-model="form.mat_num"
          label="Matriculation number"
          :error-messages="errsFor('mat_num')"
          :disabled="submitting"
          autocomplete="username"
          inputmode="numeric"
        />
        <v-text-field
          v-model="form.password"
          label="Password"
          type="password"
          :error-messages="errsFor('password')"
          :disabled="submitting"
          autocomplete="current-password"
        />
        <v-btn
          type="submit"
          color="primary"
          :loading="submitting"
          style="margin-top: 1rem"
        >
          Restore
        </v-btn>
      </v-form>
    </v-card>
  </div>
</template>
