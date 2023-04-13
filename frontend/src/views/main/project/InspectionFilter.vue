<template>
  <v-menu
      v-model="menu"
      :close-on-content-click="false"
      disable-keys
      offset-x right
      :nudge-left="dirtyFilterValue.type === RowFilterType.CUSTOM ? 1000 : 300"
      :nudge-bottom="28"
      :max-width="dirtyFilterValue.type === RowFilterType.CUSTOM ? 1000 : 300"
      min-width="300"
  >
    <template v-slot:activator="{ on, attrs }">
      <v-btn
          outlined
          tile
          small
          v-bind="attrs"
          v-on="on"
      >
        <v-icon left>
          {{ filter.type === RowFilterType.ALL ? 'mdi-filter-outline' : 'mdi-filter' }}
        </v-icon>
        {{ filterTypesByKey[filter.type].label }}
      </v-btn>
    </template>

    <v-form @submit.p.prevent="save">
      <v-card>
        <v-row no-gutters>
          <v-col v-if="dirtyFilterValue.type === RowFilterType.CUSTOM" class="left-column d-flex"
                 @keydown.tab="e=>e.stopPropagation()"
          >
            <CustomInspectionFilter
                :is-target-available="isTargetAvailable"
                :labels="labels"
                :model-type="modelType"
                v-model="dirtyFilterValue"
            />
          </v-col>
          <v-col class="right-column">
            <v-list dense class="pa-0">
              <v-list-item
                  @click="selectFilter(item)"
                  class="tile"
                  :class="{'selected': dirtyFilterValue.type === item.value}"
                  v-for="item in filterTypes"
                  :key="item.value"
                  :disabled="item.disabled"
                  link
              >
                <v-list-item-title>{{ item.label }}</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-col>
        </v-row>

        <v-card-actions class="actions-section" v-show="dirtyFilterValue.type === RowFilterType.CUSTOM">
          <v-spacer></v-spacer>

          <v-btn
              text
              @click="menu = false"
          >
            Cancel
          </v-btn>
          <v-btn
              color="primary"
              text
              type="submit"
          >
            Save
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-form>
  </v-menu>

</template>

<!-- Migrate to Composition API -->
<script setup lang="ts">
import {ref, watch, onMounted} from "vue";
import { isClassification } from "@/ml-utils";
import {Filter, ModelType, RowFilterType} from "@/generated-sources";
import CustomInspectionFilter from "./CustomInspectionFilter.vue";
import _ from "lodash";
import mixpanel from "mixpanel-browser";
import {anonymize} from "@/utils";

interface FilterType {
  label: string;
  value: RowFilterType;
  disabled?: boolean;
  description?: string;
}

interface Props {
  modelType: ModelType;
  isTargetAvailable: boolean;
  labels: string[];
}

const props = withDefaults(defineProps<Props>(), {
  isTargetAvailable: false
});

const menu = ref(false);
const filter = ref(initFilter());
const dirtyFilterValue = ref(initFilter());

const filterTypes: FilterType[] = [
  {value: RowFilterType.ALL, label: 'All', description: 'Entire dataset'},
  {
    value: RowFilterType.CORRECT,
    label: isClassification(props.modelType) ? 'Correct Predictions' : 'Closest predictions (top 15%)',
    disabled: !props.isTargetAvailable,
    description: isClassification(props.modelType) ?
        'Predicted value is equal to actual value in dataset target column' :
        'Top 15% of most accurate predictions'
  },
  {
    value: RowFilterType.WRONG,
    label: isClassification(props.modelType) ? 'Incorrect Predictions' : 'Most distant predictions (top 15%)',
    disabled: !props.isTargetAvailable
  },
  {value: RowFilterType.BORDERLINE, label: 'Borderline', disabled: !props.isTargetAvailable},
  {value: RowFilterType.CUSTOM, label: 'Custom'}
];

const filterTypesByKey = _.keyBy(filterTypes, e => e.value);

const emit = defineEmits(['input']);

watch(menu, (nv) => {
  if (nv) {
    dirtyFilterValue.value = _.cloneDeep(filter.value);
  }
});

function initFilter(): Filter {
  return {
    type: RowFilterType.ALL
  }
}

function selectFilter(filter: FilterType) {
    if (dirtyFilterValue.value) {
      dirtyFilterValue.value.type = filter.value;
      if (dirtyFilterValue.value.type !== RowFilterType.CUSTOM) {
        save();
      }
    }
}

function save() {
    menu.value = false;
    filter.value = _.cloneDeep(dirtyFilterValue.value);
    if (filter.value) {
      mixpanel.track('Inspection filter', {
        'selectedFilter': filter.value.type,
        'minThreshold': filter.value.minThreshold,
        'maxThreshold': filter.value.maxThreshold,
        'maxDiffThreshold': filter.value.maxDiffThreshold,
        'minDiffThreshold': filter.value.minDiffThreshold,
        'targetLabel': anonymize(filter.value.targetLabel),
        'predictedLabel': anonymize(filter.value.predictedLabel),
        'thresholdLabel': anonymize(filter.value.thresholdLabel),
      });
    }
    emit("input", filter)
  }

onMounted(() => {
  emit("input", filter); // send an initial value outside
});
</script>

<style scoped lang="scss">
@import "src/styles/colors.scss";

.right-column {
  max-width: 300px;
  min-width: 300px;
}

.left-column {
  min-width: 700px;
  border-right: 1px solid lightgrey;
}

.v-list-item__title {
  white-space: break-spaces;
}

.actions-section {
  border-top: 1px solid lightgrey;
}

.tile {
  cursor: pointer;

  &.selected {
    background: $selected;
    color: $color-giskard-main !important;
  }

  &:hover {
    background: $hover;
  }
}

.filter-description {
  color: lightgrey;
  font-weight: 0;
}

</style>