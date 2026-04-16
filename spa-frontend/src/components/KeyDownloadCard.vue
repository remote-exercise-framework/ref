<script setup lang="ts">
import { computed, ref } from 'vue';
import type { KeyResult } from '../api/registration';

const props = withDefaults(
  defineProps<{ result: KeyResult; variant?: 'register' | 'restore' }>(),
  { variant: 'register' },
);

const pubCopied = ref(false);
const privCopied = ref(false);

// Pick the filename `ssh-keygen` would default to for this key's algorithm
// so downloaded files reflect the actual key type (ed25519/ecdsa/rsa/dsa).
function sshKeyBasename(pubkey: string | null | undefined): string {
  if (!pubkey) return 'id_rsa';
  const algo = pubkey.trim().split(/\s+/, 1)[0] ?? '';
  if (algo === 'ssh-ed25519') return 'id_ed25519';
  if (algo.startsWith('ecdsa-sha2-')) return 'id_ecdsa';
  if (algo === 'ssh-dss') return 'id_dsa';
  return 'id_rsa';
}

const keyBasename = computed(() => sshKeyBasename(props.result.pubkey));
const pubkeyFilename = computed(() => `${keyBasename.value}.pub`);
const privkeyFilename = computed(() => keyBasename.value);

async function copy(text: string | null, flag: 'pub' | 'priv') {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    if (flag === 'pub') {
      pubCopied.value = true;
      setTimeout(() => (pubCopied.value = false), 1500);
    } else {
      privCopied.value = true;
      setTimeout(() => (privCopied.value = false), 1500);
    }
  } catch {
    /* ignore */
  }
}

const hasPrivkey = !!props.result.privkey;
</script>

<template>
  <v-card class="term-panel" style="padding: 1.5rem">
    <div class="term-eyebrow" style="margin-bottom: 0.5rem">
      // key material
    </div>
    <h2 class="term-display term-hot" style="font-size: 1.5rem; margin: 0 0 1rem">
      ACCESS GRANTED
    </h2>

    <!-- Register page: explain how the key got here. -->
    <v-alert
      v-if="props.variant === 'register' && hasPrivkey"
      type="info"
      density="compact"
      style="margin-bottom: 1.25rem"
    >
      A keypair was generated for you. Your private key is stored
      server-side — if you lose it, you can retrieve it again via
      <strong>Restore Key</strong> with your matriculation number and
      password.
    </v-alert>
    <v-alert
      v-else-if="props.variant === 'register' && !hasPrivkey"
      type="info"
      density="compact"
      style="margin-bottom: 1.25rem"
    >
      You provided your own public key. No private key is stored server-side.
    </v-alert>

    <!-- Restore Key page: the user just re-fetched an existing keypair. -->
    <v-alert
      v-else-if="props.variant === 'restore' && hasPrivkey"
      type="info"
      density="compact"
      style="margin-bottom: 1.25rem"
    >
      Your stored keypair is shown below. Download whichever key you need.
    </v-alert>
    <v-alert
      v-else-if="props.variant === 'restore' && !hasPrivkey"
      type="info"
      density="compact"
      style="margin-bottom: 1.25rem"
    >
      Only your public key is on file — you supplied your own at
      registration time, so the private key stays with you.
    </v-alert>

    <div style="display: flex; flex-direction: column; gap: 1.5rem">
      <div>
        <div class="term-eyebrow" style="margin-bottom: 0.4rem">
          public key
        </div>
        <v-textarea
          :model-value="props.result.pubkey"
          readonly
          rows="3"
          auto-grow
          hide-details
        />
        <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem">
          <v-btn
            :href="props.result.pubkey_url"
            :download="pubkeyFilename"
            prepend-icon="mdi-download"
            size="small"
          >
            Download {{ pubkeyFilename }}
          </v-btn>
          <v-btn
            size="small"
            :prepend-icon="pubCopied ? 'mdi-check' : 'mdi-content-copy'"
            @click="copy(props.result.pubkey, 'pub')"
          >
            {{ pubCopied ? 'Copied' : 'Copy' }}
          </v-btn>
        </div>
      </div>

      <div v-if="hasPrivkey">
        <div class="term-eyebrow" style="margin-bottom: 0.4rem">
          private key
        </div>
        <v-textarea
          :model-value="props.result.privkey ?? ''"
          readonly
          rows="6"
          auto-grow
          hide-details
        />
        <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem">
          <v-btn
            v-if="props.result.privkey_url"
            :href="props.result.privkey_url"
            :download="privkeyFilename"
            prepend-icon="mdi-download"
            size="small"
          >
            Download {{ privkeyFilename }}
          </v-btn>
          <v-btn
            size="small"
            :prepend-icon="privCopied ? 'mdi-check' : 'mdi-content-copy'"
            @click="copy(props.result.privkey, 'priv')"
          >
            {{ privCopied ? 'Copied' : 'Copy' }}
          </v-btn>
        </div>
      </div>
    </div>
  </v-card>
</template>
