<script setup lang="ts">
import { useContractQueries, useInputMap } from '@/hooks';
import { ref, computed, watch, onMounted } from 'vue';
import PageSection from '@/components/Simulator/PageSection.vue';
import { ArrowUpTrayIcon } from '@heroicons/vue/16/solid';
import EmptyListPlaceholder from '@/components/Simulator/EmptyListPlaceholder.vue';
import GhostBtn from '../global/GhostBtn.vue';
import { notify } from '@kyvg/vue3-notification';
import TextAreaInput from '@/components/global/inputs/TextAreaInput.vue';
import FieldError from '@/components/global/fields/FieldError.vue';
import * as calldata from '@/calldata';
import type { ContractMethodBase } from '@/types';

const props = defineProps<{
  leaderOnly: boolean;
}>();

const { contract, contractSchemaQuery, deployContract, isDeploying } =
  useContractQueries();
const inputMap = useInputMap();

const { data, isPending, isRefetching, isError } = contractSchemaQuery;
const inputParams = ref<{ [k: string]: any }>({});

const constructorInputs = computed(
  () => data.value?.ctor as ContractMethodBase | undefined,
);

const emit = defineEmits(['deployed-contract']);

const isValidDefaultState = computed(() => {
  if (mode.value === 'json') {
    // Try to parse JSON
    try {
      JSON.parse(jsonParams.value || '{}');
      return true;
    } catch (error) {
      return false;
    }
  } else {
    return true;
  }
});

const jsonParams = ref('{}');
const mode = ref<'json' | 'form'>('form');

const handleDeployContract = async () => {
  let constructorParams: calldata.CalldataEncodable[];

  if (mode.value === 'json') {
    try {
      const data = calldata.parse(jsonParams.value || '{}');
      if (!(data instanceof Array)) {
        throw new Error('constructor parameters must be an array');
      }
      constructorParams = data;
    } catch (error) {
      console.error(error);
      notify({
        title: 'Error',
        text: 'Please provide valid JSON',
        type: 'error',
      });
      return;
    }
  } else {
    constructorParams = Object.keys(inputParams.value).map((key) => {
      const val = inputParams.value[key];
      if (
        constructorInputs.value?.params?.find((x) => x[0] === key)?.[1] ===
        'string'
      ) {
        return val;
      }
      return calldata.parse(val);
    });
  }

  await deployContract(constructorParams, props.leaderOnly);

  emit('deployed-contract');
};

const setInputParams = (
  schema:
    | { params: Array<any>; kwparams: { [key: string]: any } }
    | null
    | undefined,
) => {
  console.log(schema);
  if (schema == null) {
    jsonParams.value = '{}';
    return;
  }
  const res: [string, string][] = [];
  for (const arg of schema.params) {
    res.push([arg.name, '']);
  }
  for (const [name] of Object.entries(schema.kwparams)) {
    res.push([name, '']);
  }
  jsonParams.value = JSON.stringify(Object.fromEntries(res), null, 2);
  console.log(jsonParams.value);
};

const toggleMode = () => {
  mode.value = mode.value === 'json' ? 'form' : 'json';
  if (mode.value === 'json') {
    throw new Error('json is unsupported right now');
  } else {
    inputParams.value = {};
  }
};

watch(
  () => constructorInputs.value,
  (newValue) => {
    setInputParams(newValue || { params: [], kwparams: {} });
  },
);

onMounted(() => {
  if (constructorInputs.value) {
    setInputParams(constructorInputs.value);
  }
});

const hasConstructorInputs = computed(
  () =>
    constructorInputs.value &&
    constructorInputs.value.params.length +
      Object.keys(constructorInputs.value.kwparams).length >
      0,
);
</script>

<template>
  <PageSection>
    <template #title
      >Constructor Inputs
      <Loader v-if="isRefetching" :size="14" />
    </template>

    <template #actions>
      <GhostBtn
        v-if="hasConstructorInputs"
        @click="toggleMode"
        class="p-1 text-xs"
      >
        {{ mode === 'json' ? 'Inputs' : 'JSON' }}
      </GhostBtn>
    </template>

    <ContentLoader v-if="isPending" />

    <Alert v-else-if="isError" error> Could not load contract schema. </Alert>

    <template v-else-if="data">
      <EmptyListPlaceholder v-if="!hasConstructorInputs">
        No constructor inputs.
      </EmptyListPlaceholder>

      <div
        v-else
        class="flex flex-col justify-start gap-1"
        :class="isDeploying && 'pointer-events-none opacity-60'"
      >
        <template v-if="mode === 'form'">
          <div v-for="input in constructorInputs?.params || []" :key="input[0]">
            <component
              :is="inputMap.getComponent(input[0])"
              v-model="inputParams[input[0]]"
              :name="input[0]"
              :placeholder="input[1]"
              :label="input[0]"
            />
          </div>
          <div
            v-for="input in Object.keys(constructorInputs?.kwparams || {})"
            :key="input[0]"
          >
            <component
              :is="
                inputMap.getComponent(
                  typeof constructorInputs?.kwparams?.[input] === 'string'
                    ? constructorInputs.kwparams[input]
                    : `${constructorInputs?.kwparams?.[input]}`,
                )
              "
              v-model="inputParams[input]"
              :name="input"
              :placeholder="
                inputMap.getComponent(
                  typeof constructorInputs?.kwparams?.[input] === 'string'
                    ? constructorInputs?.kwparams?.[input]
                    : `${constructorInputs?.kwparams?.[input]}`,
                )
              "
              :label="input"
            />
          </div>
        </template>

        <TextAreaInput
          v-if="mode === 'json'"
          id="state"
          name="state"
          :rows="5"
          :invalid="!isValidDefaultState"
          v-model="jsonParams"
        />
        <FieldError v-if="!isValidDefaultState"
          >Please enter valid JSON.</FieldError
        >
      </div>

      <Btn
        testId="btn-deploy-contract"
        @click="handleDeployContract"
        :loading="isDeploying"
        :disabled="!isValidDefaultState"
        :icon="ArrowUpTrayIcon"
        v-tooltip="!isValidDefaultState && 'Provide default state'"
      >
        <template v-if="isDeploying">Deploying...</template>
        <template v-else>Deploy {{ contract?.name }}</template>
      </Btn>
    </template>
  </PageSection>
</template>
