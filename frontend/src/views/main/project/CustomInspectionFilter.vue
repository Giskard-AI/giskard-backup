<template>
  <v-container class="main align-self-center">
    <v-row align="center" v-if="!isClassification">
      <v-col cols="5">Predicted value is between</v-col>
      <v-col>
        <v-text-field
            v-model='value.minThreshold'
            hide-details
            class="pa-0 ma-0"
            type='number'
        ></v-text-field>
      </v-col>
      <v-col cols="1" class="text-center">and</v-col>
      <v-col>
        <v-text-field
            class="pa-0 ma-0"
            v-model='value.maxThreshold'
            hide-details
            type='number'
        ></v-text-field>
      </v-col>
    </v-row>
    <v-row align="center" v-if="!isClassification && isTargetAvailable">
      <v-col cols="5">Actual value is between</v-col>
      <v-col>
        <v-text-field
            class="pa-0 ma-0"
            v-model='value.minLabelThreshold'
            hide-details
            type='number'
        >
        </v-text-field>
      </v-col>
      <v-col cols="1" class="text-center">and</v-col>
      <v-col>
        <v-text-field
            class="pa-0 ma-0"
            v-model='value.maxLabelThreshold'
            hide-details
            type='number'
        ></v-text-field>
      </v-col>
    </v-row>
    <v-row align="center" v-if="!isClassification && isTargetAvailable">
      <v-col cols="5">Diff percentage value is between</v-col>
      <v-col>
        <v-text-field
            class="pa-0 ma-0"
            v-model='value.minDiffThreshold'
            step='0.1'
            hide-details
            type='number'
        >
          <template v-slot:append>
            %
          </template>
        </v-text-field>
      </v-col>
      <v-col cols="1" class="text-center">and</v-col>
      <v-col>
        <v-text-field
            class="pa-0 ma-0"
            v-model='value.maxDiffThreshold'
            step='0.1'
            hide-details
            type='number'
        >
          <template v-slot:append>
            %
          </template>
        </v-text-field>
      </v-col>
    </v-row>
    <v-row align="center" v-if="isClassification">
      <v-col v-if="isTargetAvailable && value.targetLabel">
        <MultiSelector label='Actual Labels' :options='labels'
                       :selected-options.sync='value.targetLabel'/>
      </v-col>
      <v-col v-if="value.predictedLabel">
        <MultiSelector label='Predicted Labels' :options='labels' v-if="value.predictedLabel"
                       :selected-options.sync='value.predictedLabel'/>
      </v-col>
    </v-row>
    <v-row align="center" v-if="isClassification">
      <v-col>Probability of</v-col>
      <v-col cols="3">
        <v-select
            clearable
            class="pa-0 ma-0"
            :items='labels'
            v-model='value.thresholdLabel'
            hide-details
        ></v-select>
      </v-col>
      <v-col class="text-center">is between :</v-col>
      <v-col>
        <v-text-field
            class="pa-0 ma-0"
            v-model='value.minThreshold'
            hide-details
            type='number'
        >
          <template v-slot:append>%</template>
        </v-text-field>
      </v-col>
      <v-col cols="1" class="text-center">and</v-col>
      <v-col>
        <v-text-field
            class="pa-0 ma-0"
            v-model='value.maxThreshold'
            hide-details
            type='number'
        >
          <template v-slot:append>%</template>
        </v-text-field>
      </v-col>
    </v-row>
  </v-container>
</template>

<script lang="ts">
import Component from "vue-class-component";
import Vue from "vue";
import {Prop} from "vue-property-decorator";
import {Filter, ModelType} from "@/generated-sources";
import {isClassification} from "@/ml-utils";
import MultiSelector from "@/views/main/utils/MultiSelector.vue";

@Component({components: {MultiSelector}})
export default class CustomInspectionFilter extends Vue {
  @Prop({required: true}) modelType!: ModelType;
  @Prop({required: true}) labels!: string[];
  @Prop({default: false}) isTargetAvailable!: boolean;
  @Prop() value!: Filter;

  get isClassification() {
    return isClassification(this.modelType);
  }

  mounted() {
    this.value.predictedLabel = this.value.predictedLabel || [];
    this.value.targetLabel = this.value.targetLabel || [];
    this.$emit('input', this.value);
    this.$forceUpdate();
  }
}

</script>

<style scoped lang="scss">
.main {
  width: 100%;
  font-size: 14px;
}

::v-deep .v-select__selections {
  white-space: nowrap;
  display: flex;
  flex-wrap: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

::v-deep .v-chip--select {
  min-width: 32px;

  .v-chip__content {
    overflow: hidden;
  }
}

::v-deep .v-input__append-inner {
  align-self: auto;
}
</style>