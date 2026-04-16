<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import type { FieldErrors } from '../api/client';
import { ApiError } from '../api/client';
import {
  getRegistrationMeta,
  submitRegistration,
  type KeyResult,
  type RegistrationMeta,
} from '../api/registration';
import KeyDownloadCard from '../components/KeyDownloadCard.vue';

const meta = ref<RegistrationMeta | null>(null);
const loadingMeta = ref(true);
const metaError = ref<string | null>(null);

const form = reactive({
  mat_num: '',
  firstname: '',
  surname: '',
  password: '',
  password_rep: '',
  pubkey: '',
  group_name: '',
});

const submitting = ref(false);
const formError = ref<string | null>(null);
const fieldErrors = ref<FieldErrors>({});
const result = ref<KeyResult | null>(null);

const AUTO_ASSIGN_VALUE = '';

const groupItems = computed(() => {
  const base = (meta.value?.groups ?? []).map((g) => ({
    title: g.full ? `${g.name} (full ${g.count}/${g.max})` : `${g.name} (${g.count}/${g.max})`,
    value: g.name,
    props: { disabled: g.full },
  }));
  return [
    { title: 'Auto Assigned', value: AUTO_ASSIGN_VALUE, auto: true },
    ...base,
  ];
});

function resetGroup() {
  // Clearable's default behaviour sets the model to null; force it back
  // to the Auto Assigned sentinel so the v-model stays bound to a real
  // item and the selection slot can keep rendering "Auto Assigned".
  form.group_name = AUTO_ASSIGN_VALUE;
}

const passwordHint = computed(() => {
  const rules = meta.value?.password_rules;
  if (!rules) return '';
  return (
    `Password must be at least ${rules.min_length} characters and use at ` +
    `least ${rules.min_classes} of: digits, uppercase, lowercase, symbols.`
  );
});

function errsFor(field: string): string[] {
  return fieldErrors.value[field] ?? [];
}

onMounted(async () => {
  try {
    meta.value = await getRegistrationMeta();
  } catch (e) {
    metaError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loadingMeta.value = false;
  }
});

async function onSubmit() {
  formError.value = null;
  fieldErrors.value = {};
  submitting.value = true;
  try {
    result.value = await submitRegistration({
      mat_num: form.mat_num,
      firstname: form.firstname,
      surname: form.surname,
      password: form.password,
      password_rep: form.password_rep,
      pubkey: form.pubkey || undefined,
      group_name: meta.value?.groups_enabled ? form.group_name : undefined,
    });
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
      <h2 class="term-section-title">[ registration ]</h2>
      <span class="term-eyebrow">// get your key</span>
    </div>

    <v-progress-circular
      v-if="loadingMeta"
      indeterminate
      color="secondary"
    />

    <v-alert v-else-if="metaError" type="error" variant="tonal">
      Failed to load registration metadata: {{ metaError }}
    </v-alert>

    <v-alert
      v-else-if="meta && !meta.registration_enabled && !result"
      type="warning"
      variant="tonal"
      class="term-form-box"
      style="margin-bottom: 1rem"
    >
      Registration is currently disabled. Please contact the staff if you
      need to register.
    </v-alert>

    <div v-if="result" class="term-form-box">
      <KeyDownloadCard :result="result" />
    </div>

    <v-card
      v-else-if="meta"
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
          :disabled="submitting || !meta.registration_enabled"
          autocomplete="username"
          inputmode="numeric"
        />
        <v-text-field
          v-model="form.firstname"
          label="First name"
          :error-messages="errsFor('firstname')"
          :disabled="submitting || !meta.registration_enabled"
          autocomplete="given-name"
        />
        <v-text-field
          v-model="form.surname"
          label="Surname"
          :error-messages="errsFor('surname')"
          :disabled="submitting || !meta.registration_enabled"
          autocomplete="family-name"
        />
        <v-text-field
          v-model="form.password"
          label="Password"
          type="password"
          :hint="passwordHint"
          persistent-hint
          :error-messages="errsFor('password')"
          :disabled="submitting || !meta.registration_enabled"
          autocomplete="new-password"
        />
        <v-text-field
          v-model="form.password_rep"
          label="Repeat password"
          type="password"
          :error-messages="errsFor('password_rep')"
          :disabled="submitting || !meta.registration_enabled"
          autocomplete="new-password"
        />
        <v-textarea
          v-model="form.pubkey"
          label="Public SSH key (optional — leave empty to generate)"
          hint="Supported: RSA, Ed25519, ECDSA (OpenSSH format)."
          persistent-hint
          :error-messages="errsFor('pubkey')"
          :disabled="submitting || !meta.registration_enabled"
          rows="3"
          auto-grow
        />
        <v-select
          v-if="meta.groups_enabled"
          v-model="form.group_name"
          :items="groupItems"
          label="Group"
          :error-messages="errsFor('group_name')"
          :disabled="submitting || !meta.registration_enabled"
          :clearable="form.group_name !== AUTO_ASSIGN_VALUE"
          clear-icon="mdi-close"
          @click:clear.stop="resetGroup"
        >
          <template #selection="{ item }">
            <span
              :class="{ 'term-placeholder': item.raw.value === AUTO_ASSIGN_VALUE }"
            >
              {{ item.raw.title }}
            </span>
          </template>
        </v-select>

        <v-btn
          type="submit"
          color="primary"
          :loading="submitting"
          :disabled="!meta.registration_enabled"
          style="margin-top: 1rem"
        >
          Get Key
        </v-btn>
      </v-form>
    </v-card>
  </div>
</template>
