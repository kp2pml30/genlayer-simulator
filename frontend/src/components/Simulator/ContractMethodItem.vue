<script setup lang="ts">
import type { ContractMethod } from '@/types';
import { onMounted, ref, computed } from 'vue';
import { Collapse } from 'vue-collapsed';
import { useInputMap } from '@/hooks';
import { notify } from '@kyvg/vue3-notification';
import { ChevronDownIcon } from '@heroicons/vue/16/solid';
import { useEventTracking, useContractQueries } from '@/hooks';
import * as calldata from '@/calldata';

const { callWriteMethod, callReadMethod, contract } = useContractQueries();
const { trackEvent } = useEventTracking();

const inputMap = useInputMap();

const props = defineProps<{
  name: string;
  method: ContractMethod;
  methodType: 'read' | 'write';
  leaderOnly: boolean;
}>();

const isExpanded = ref(false);
const inputs = ref<{ [k: string]: string }>({});
const responseMessage = ref('');

const missingParams = computed(() => {
  return props.method.params.some(
    (input: any) =>
      typeof inputs.value[input.name] === 'string' &&
      inputs.value[input.name].trim() === '',
  );
});

const getArgs = () => {
  return Object.keys(inputs.value).map((key) => {
    if (props.method.params.find((v) => v[0] == key)?.[1] === 'string') {
      return inputs.value[key];
    }
    return calldata.parse(inputs.value[key]);
  });
};

const handleCallReadMethod = async () => {
  responseMessage.value = '';

  try {
    const result = await callReadMethod(props.name, getArgs());

    responseMessage.value =
      typeof result === 'string' ? result : JSON.stringify(result);

    trackEvent('called_read_method', {
      contract_name: contract.value?.name || '',
      method_name: props.name,
    });
  } catch (error) {
    notify({
      title: 'Error',
      text: (error as Error)?.message || 'Error getting contract state',
      type: 'error',
    });
  }
};

const handleCallWriteMethod = async () => {
  await callWriteMethod({
    method: props.name,
    args: Object.values(inputs.value),
    leaderOnly: props.leaderOnly,
  });

  resetInputs();

  notify({
    text: 'Write method called',
    type: 'success',
  });

  trackEvent('called_write_method', {
    contract_name: contract.value?.name || '',
    method_name: props.name,
  });
};

const resetInputs = () => {
  props.method.params.forEach((input) => {
    inputs.value[input[0]] = '';
  });
  Object.keys(props.method.kwparams).forEach((input) => {
    inputs.value[input] = '';
  });
};

onMounted(() => {
  resetInputs();
});
</script>

<template>
  <div
    class="dark:bg-g flex flex-col overflow-hidden rounded-md bg-slate-100 dark:bg-gray-700"
  >
    <button
      class="flex grow flex-row items-center justify-between bg-slate-200 p-2 text-xs hover:bg-slate-300 dark:bg-slate-600 dark:hover:bg-slate-500"
      @click="isExpanded = !isExpanded"
      :data-testid="`expand-method-btn-${name}`"
    >
      <div class="truncate">
        {{ name }}
      </div>

      <ChevronDownIcon
        class="h-4 w-4 opacity-70 transition-all duration-300"
        :class="isExpanded && 'rotate-180'"
      />
    </button>

    <Collapse :when="isExpanded">
      <div class="flex flex-col items-start gap-2 p-2">
        <component
          v-for="input in method.params"
          :key="input[0]"
          :is="
            inputMap.getComponent(
              typeof input[1] === 'string' ? input[1] : `${input[1]}`,
            )
          "
          v-model="inputs[input[0]]"
          :name="input[0]"
          :label="input[0]"
          :placeholder="typeof input[1] === 'string' ? input[1] : `${input[1]}`"
        />

        <div>
          <Btn
            v-if="methodType === 'read'"
            @click="handleCallReadMethod"
            tiny
            :data-testid="`read-method-btn-${name}`"
            :disabled="missingParams"
            v-tooltip="missingParams ? 'All parameters are required' : ''"
            >Call Contract</Btn
          >

          <Btn
            v-if="methodType === 'write'"
            @click="handleCallWriteMethod"
            tiny
            :data-testid="`write-method-btn-${name}`"
            >Send Transaction</Btn
          >
        </div>

        <div v-if="responseMessage" class="w-full break-all text-sm">
          <div class="mb-1 text-xs font-medium">Response:</div>
          <div
            :data-testid="`method-response-${name}`"
            class="w-full rounded bg-white p-1 font-mono text-xs dark:bg-slate-600"
          >
            {{ responseMessage }}
          </div>
        </div>
      </div>
    </Collapse>
  </div>
</template>
