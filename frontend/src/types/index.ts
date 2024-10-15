export * from './results';
export * from './requests';
export * from './responses';
export * from './store';
export * from './events';

export interface ValidatorModel {
  address: string;
  config: any;
  id: number;
  model: string;
  provider: string;
  stake: number;
  updated_at: string;
  plugin: string;
  plugin_config: Record<string, any>;
}

export interface NewValidatorDataModel {
  config: string;
  model: string;
  provider: string;
  stake: number;
}

export type ContractParamsArraySchemaElement =
  | ContractParamsSchema
  | { $rep: ContractParamsSchema };

export type ContractParamsSchema =
  | 'null'
  | 'bool'
  | 'int'
  | 'address'
  | 'string'
  | 'bytes'
  | 'any'
  | 'array'
  | 'dict'
  | { $or: ContractParamsSchema[] }
  | { $dict: ContractParamsSchema }
  | { [key: string]: ContractParamsSchema }
  | ContractParamsArraySchemaElement[];

export interface ContractMethodBase {
  params: [string, ContractParamsSchema][];
  kwparams: { [key: string]: ContractParamsSchema };
}

export interface ContractMethod extends ContractMethodBase {
  ret: ContractParamsSchema;
  readonly: boolean;
}

export type Address = `0x${string}`;
